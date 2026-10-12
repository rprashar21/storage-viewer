"""Read-only logical-size scanner. No file contents are opened."""
import heapq
import os
import stat
import threading
import time
from pathlib import Path

TOP_FILES = 20
CATEGORIES = {
    'Images': {'.png', '.jpg', '.jpeg', '.gif', '.heic', '.webp', '.tiff', '.bmp', '.svg', '.raw', '.psd'},
    'Video': {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.webm', '.wmv'},
    'Audio': {'.mp3', '.m4a', '.wav', '.flac', '.aac', '.aiff', '.ogg'},
    'Documents': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.pages', '.numbers', '.key',
                  '.txt', '.md', '.rtf', '.csv', '.epub'},
    'Archives': {'.zip', '.tar', '.gz', '.tgz', '.rar', '.7z', '.dmg', '.pkg', '.iso', '.bz2', '.xz'},
}
EXT_CATEGORY = {ext: name for name, exts in CATEGORIES.items() for ext in exts}


class ScanJob:
    def __init__(self, root):
        self.root = Path(root).expanduser().absolute()
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.state = {'path': str(self.root), 'status': 'scanning', 'rows': [],
                      'files': 0, 'bytes': 0, 'errors': 0, 'links': 0, 'mounts_skipped': 0,
                      'error_samples': [], 'top_files': [], 'types': {}, 'current': '', 'elapsed': 0}
        self.started = time.monotonic()
        self.finished = None
        try:
            self.root_dev = os.stat(self.root).st_dev
        except OSError:
            self.root_dev = None

    def snapshot(self):
        with self.lock:
            result = dict(self.state)
            result['rows'] = [dict(row) for row in self.state['rows']]
            result['error_samples'] = list(self.state['error_samples'])
            result['types'] = dict(self.state['types'])
            result['top_files'] = [{'bytes': b, 'path': p} for b, p in sorted(self.state['top_files'], reverse=True)]
        result['elapsed'] = round((self.finished or time.monotonic()) - self.started, 1)
        result['rows'].sort(key=lambda r: (-r['bytes'], r['name'].casefold(), r['name']))
        return result

    def _error(self, path, exc):
        with self.lock:
            self.state['errors'] += 1
            if len(self.state['error_samples']) < 20:
                self.state['error_samples'].append(f'{path}: {exc}')

    def run(self):
        try:
            self._run()
        except Exception as exc:
            self._error(self.root, exc)
            with self.lock:
                self.state['status'] = 'failed'
        finally:
            self.finished = time.monotonic()

    def _run(self):
        # Stack traversal keeps no recursive Python call chain; links are skipped.
        try:
            # Pass 1 lists every immediate child at once so rows appear before any size work.
            pending = []
            with os.scandir(self.root) as items:
                for item in items:
                    if self.cancelled.is_set():
                        break
                    try:
                        info = item.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            with self.lock:
                                self.state['links'] += 1
                            continue
                        kind = 'folder' if stat.S_ISDIR(info.st_mode) else 'file'
                        if kind == 'folder' and self._other_volume(info):
                            continue
                        if kind == 'file' and not stat.S_ISREG(info.st_mode):
                            continue
                        row = {'name': item.name, 'path': item.path, 'kind': kind,
                               'bytes': 0, 'files': 0, 'errors': 0, 'status': 'queued'}
                        with self.lock:
                            self.state['rows'].append(row)
                        pending.append((item, info, row))
                    except OSError as exc:
                        self._error(item.path, exc)
                        with self.lock:
                            self.state['rows'].append({'name': item.name, 'path': item.path, 'kind': 'file',
                                                       'bytes': 0, 'files': 0, 'errors': 1, 'status': 'unavailable'})
            # Pass 2 fills in sizes child by child.
            for item, info, row in pending:
                if self.cancelled.is_set():
                    break
                with self.lock:
                    row['status'] = 'scanning'
                errors_before = self.state['errors']
                if row['kind'] == 'file':
                    self._add(row, info.st_size, item.path)
                else:
                    self._folder(item.path, row)
                with self.lock:
                    row['errors'] = self.state['errors'] - errors_before
                    row['status'] = ('partial' if self.cancelled.is_set() or row['errors']
                                     else 'complete')
        except OSError as exc:
            self._error(self.root, exc)
        with self.lock:
            for r in self.state['rows']:
                if r['status'] in ('queued', 'scanning'):
                    r['status'] = 'not scanned'
            self.state['current'] = ''
            self.state['status'] = ('cancelled' if self.cancelled.is_set() else
                                    'partial' if self.state['errors'] else 'complete')

    def _other_volume(self, info):
        if self.root_dev is not None and info.st_dev != self.root_dev:
            with self.lock:
                self.state['mounts_skipped'] += 1
            return True
        return False

    def _add(self, row, size, path):
        category = EXT_CATEGORY.get(os.path.splitext(path)[1].lower(), 'Other')
        with self.lock:
            types = self.state['types']
            types[category] = types.get(category, 0) + size
            top = self.state['top_files']
            if len(top) < TOP_FILES:
                heapq.heappush(top, (size, path))
            elif size > top[0][0]:
                heapq.heapreplace(top, (size, path))
            row['bytes'] += size
            row['files'] += 1
            self.state['bytes'] += size
            self.state['files'] += 1

    def _folder(self, path, row):
        stack = [path]
        while stack and not self.cancelled.is_set():
            current = stack.pop()
            with self.lock:
                self.state['current'] = current
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if self.cancelled.is_set():
                            return
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(info.st_mode):
                                with self.lock:
                                    self.state['links'] += 1
                            elif stat.S_ISDIR(info.st_mode):
                                if not self._other_volume(info):
                                    stack.append(entry.path)
                            elif stat.S_ISREG(info.st_mode):
                                self._add(row, info.st_size, entry.path)
                        except OSError as exc:
                            self._error(entry.path, exc)
            except OSError as exc:
                self._error(current, exc)
