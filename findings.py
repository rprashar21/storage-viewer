"""Read-only cleanup candidates. Nothing is modified. Hashing reads file bytes for duplicates only."""
import filecmp
import hashlib
import os
import stat
import threading
import time

from ignore import is_ignored

INSTALLER_EXT = {'.dmg', '.pkg', '.iso', '.zip', '.tar', '.gz', '.tgz', '.rar', '.7z'}
MAX_ITEMS = 100
DEV_MANIFEST = {'node_modules': 'package.json', 'Pods': 'Podfile', 'target': 'Cargo.toml'}
DERIVED = os.sep.join(['Library', 'Developer', 'Xcode', 'DerivedData'])


class FindingsJob:
    def __init__(self, root, large=100_000_000, old_days=180, old_min=10_000_000, dup_min=1_000_000, ignore=()):
        self.ignore = list(ignore)
        self.root, self.large, self.old_days, self.old_min, self.dup_min = root, large, old_days, old_min, dup_min
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.state = {'path': str(root), 'status': 'scanning', 'phase': 'walking', 'findings': [],
                      'files': 0, 'errors': 0, 'measured_at': None}

    def snapshot(self):
        with self.lock:
            out = dict(self.state)
            out['findings'] = [dict(f) for f in self.state['findings']]
        return out

    def run(self):
        try:
            files, empties, dev = self._walk()
            now = time.time()
            cutoff = now - self.old_days * 86400
            top = lambda rows: sorted(rows, key=lambda r: -r['bytes'])[:MAX_ITEMS]
            rec = lambda f: {'path': f[0], 'bytes': f[1], 'mtime': f[2]}
            out = [
                self._finding('large', 'Large files', f'Files of {self.large // 1_000_000} MB or more.',
                              top([rec(f) for f in files if f[1] >= self.large])),
                self._finding('old', 'Old large files',
                              f'Not modified for {self.old_days}+ days and {self.old_min // 1_000_000} MB or more. Old does not mean unused.',
                              top([rec(f) for f in files if f[2] < cutoff and f[1] >= self.old_min])),
                self._finding('installers', 'Installers and archives', 'Disk images, packages and archives by extension.',
                              top([rec(f) for f in files if os.path.splitext(f[0])[1].lower() in INSTALLER_EXT])),
                self._finding('dev', 'Developer build clutter',
                              'Folders that build tools recreate: node_modules (npm install), Pods (pod install), Rust target (cargo build) and Xcode DerivedData (rebuilt on the next build). Anything you edited inside them is lost, and recreating them takes time.',
                              top(self._dev_items(dev))),
                self._finding('empty', 'Empty folders', 'Folders with no entries.',
                              [{'path': p, 'bytes': 0, 'mtime': None} for p in sorted(empties)[:MAX_ITEMS]]),
            ]
            with self.lock:
                self.state['findings'] = out
                self.state['phase'] = 'hashing'
            dups = self._duplicates(files)
            with self.lock:
                self.state['findings'].append(dups)
                self.state['phase'] = 'done'
                self.state['measured_at'] = now
                self.state['status'] = ('cancelled' if self.cancelled.is_set() else
                                        'partial' if self.state['errors'] else 'complete')
        except Exception as exc:
            with self.lock:
                self.state['errors'] += 1
                self.state['status'] = 'failed'
                self.state['error'] = str(exc)

    def _finding(self, rule, title, reason, items):
        return {'rule': rule, 'title': title, 'reason': reason, 'items': items,
                'bytes': sum(i['bytes'] for i in items), 'estimate': False,
                'note': 'Listing capped at %d items.' % MAX_ITEMS if len(items) >= MAX_ITEMS else ''}

    def _dev_items(self, dev):
        out = []
        for path, kind in dev:
            if self.cancelled.is_set():
                break
            try:
                mtime = os.lstat(path).st_mtime
            except OSError:
                continue
            out.append({'path': path, 'bytes': self._dir_size(path), 'mtime': mtime, 'kind': kind})
        return out

    def _dir_size(self, path):
        total, stack = 0, [path]
        while stack and not self.cancelled.is_set():
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            info = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            stack.append(e.path)
                        elif stat.S_ISREG(info.st_mode):
                            total += info.st_size
            except OSError:
                self._err()
        return total

    @staticmethod
    def _dev_kind(parent, entry):
        manifest = DEV_MANIFEST.get(entry.name)
        if manifest and os.path.exists(os.path.join(parent, manifest)):
            return entry.name
        return None

    def _err(self):
        with self.lock:
            self.state['errors'] += 1

    def _walk(self):
        files, empties, dev, stack = [], [], [], [str(self.root)]
        try:
            root_dev = os.stat(self.root).st_dev
        except OSError:
            root_dev = None
        while stack and not self.cancelled.is_set():
            cur = stack.pop()
            count = 0
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        if self.ignore and is_ignored(e.path, self.ignore):
                            continue
                        count += 1
                        try:
                            info = e.stat(follow_symlinks=False)
                        except OSError:
                            self._err()
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if e.path.endswith(os.sep + DERIVED):
                                try:
                                    dev.extend((c.path, 'DerivedData') for c in os.scandir(e.path)
                                               if c.is_dir(follow_symlinks=False) and not is_ignored(c.path, self.ignore))
                                except OSError:
                                    self._err()
                            elif self._dev_kind(cur, e):
                                dev.append((e.path, e.name))
                            elif root_dev is None or info.st_dev == root_dev:
                                stack.append(e.path)
                        elif stat.S_ISREG(info.st_mode):
                            files.append((e.path, info.st_size, info.st_mtime))
                            with self.lock:
                                self.state['files'] += 1
            except OSError:
                self._err()
                continue
            if count == 0 and cur != str(self.root):
                empties.append(cur)
        return files, empties, dev

    def _duplicates(self, files):
        by_size = {}
        for path, size, mtime in files:
            if size >= self.dup_min:
                by_size.setdefault(size, []).append((path, mtime))
        groups = []
        for size, members in by_size.items():
            if len(members) < 2:
                continue
            by_hash = {}
            for path, mtime in members:
                if self.cancelled.is_set():
                    break
                try:
                    h = hashlib.sha256()
                    with open(path, 'rb') as fh:
                        for chunk in iter(lambda: fh.read(1 << 20), b''):
                            h.update(chunk)
                    by_hash.setdefault(h.hexdigest(), []).append((path, mtime))
                except OSError:
                    self._err()
            for same in by_hash.values():
                if len(same) < 2:
                    continue
                verified = [same[0]]
                for cand in same[1:]:
                    try:
                        if filecmp.cmp(same[0][0], cand[0], shallow=False):
                            verified.append(cand)
                    except OSError:
                        self._err()
                if len(verified) > 1:
                    groups.append((size, verified))
        groups.sort(key=lambda g: -g[0] * (len(g[1]) - 1))
        items = []
        for size, members in groups[:MAX_ITEMS]:
            for path, mtime in members:
                items.append({'path': path, 'bytes': size, 'mtime': mtime})
        estimate = sum(size * (len(m) - 1) for size, m in groups)
        return {'rule': 'duplicates', 'title': 'Exact duplicates',
                'reason': 'Files with identical content (hash plus byte comparison). Keep one copy; links and clones are not accounted for.',
                'items': items, 'bytes': estimate, 'estimate': True,
                'groups': [[m[0] for m in members] for _, members in groups[:MAX_ITEMS]],
                'note': 'Estimated reclaimable space if all but one copy of each group were removed.'}
