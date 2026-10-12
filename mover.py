"""Journalled, no-overwrite file moves with undo. Same-volume moves and copies only.

A move is os.link(src, dst) then os.unlink(src): link never overwrites, so a collision
is detected atomically. Every operation is written to the SQLite journal as 'pending'
before the filesystem is touched, and reconcile() settles anything left pending.
"""
import hashlib
import os
import shutil
import sqlite3
import stat
import time
import uuid
from pathlib import Path

from platform_adapter import get_adapter

DEFAULT_DB = get_adapter().app_support_dir() / 'journal.sqlite3'


class Journal:
    def __init__(self, path=DEFAULT_DB):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, at REAL, label TEXT, plan_id TEXT);
            CREATE TABLE IF NOT EXISTS ops(batch TEXT, idx INTEGER, kind TEXT, src TEXT, dst TEXT,
                size INTEGER, mtime REAL, ino INTEGER, status TEXT, detail TEXT);
        """)

    def close(self):
        self.db.close()

    def add_batch(self, label, plan_id):
        bid = uuid.uuid4().hex[:12]
        self.db.execute('INSERT INTO batches VALUES(?,?,?,?)', (bid, time.time(), label, plan_id))
        self.db.commit()
        return bid

    def add_op(self, batch, idx, kind, src, dst, size, mtime):
        self.db.execute('INSERT INTO ops VALUES(?,?,?,?,?,?,?,NULL,?,?)',
                        (batch, idx, kind, src, dst, size, mtime, 'pending', ''))
        self.db.commit()

    def set_op(self, batch, idx, status, detail='', dst=None, ino=None):
        self.db.execute('UPDATE ops SET status=?, detail=?, dst=COALESCE(?,dst), ino=COALESCE(?,ino) '
                        'WHERE batch=? AND idx=?', (status, detail, dst, ino, batch, idx))
        self.db.commit()

    def ops(self, batch):
        cur = self.db.execute('SELECT idx,kind,src,dst,size,mtime,ino,status,detail FROM ops WHERE batch=? ORDER BY idx',
                              (batch,))
        keys = ['idx', 'kind', 'src', 'dst', 'size', 'mtime', 'ino', 'status', 'detail']
        return [dict(zip(keys, r)) for r in cur]

    def batches(self, limit=20):
        out = []
        for bid, at, label, plan_id in self.db.execute('SELECT id,at,label,plan_id FROM batches ORDER BY at DESC LIMIT ?', (limit,)):
            ops = self.ops(bid)
            counts = {}
            for o in ops:
                counts[o['status']] = counts.get(o['status'], 0) + 1
            out.append({'id': bid, 'at': at, 'label': label, 'counts': counts,
                        'undoable': counts.get('done', 0) > 0})
        return out


def different_volume(info, target_dir):
    return os.stat(target_dir).st_dev != info.st_dev


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def numbered(path, n):
    base, ext = os.path.splitext(path)
    return f'{base} ({n}){ext}'


class Mover:
    def __init__(self, journal, trash=None):
        self.journal = journal
        if trash is None:
            trash = get_adapter().trash
        self._trash = trash

    # ---- apply -------------------------------------------------------
    def apply(self, plan, choices):
        """choices: {row_index: 'move'|'copy'}; rows not chosen or not ready are never touched."""
        batch = self.journal.add_batch(f"{plan['preset']} to {plan['dest']}", plan['id'])
        counts = {'done': 0, 'skipped': 0, 'failed': 0}
        for idx, op in sorted(choices.items()):
            row = plan['rows'][idx]
            if row['status'] != 'ready' or op not in ('move', 'copy'):
                continue
            self.journal.add_op(batch, idx, op, row['src'], row['dst'], row['bytes'], row['mtime'])
            status, detail, dst, ino = self._one(row, op, plan['conflict'])
            self.journal.set_op(batch, idx, status, detail, dst, ino)
            counts[status] = counts.get(status, 0) + 1
        return {'batch': batch, **counts}

    def _one(self, row, op, conflict):
        src = row['src']
        try:
            info = os.lstat(src)
        except OSError:
            return 'skipped', 'Source no longer exists', None, None
        if not stat.S_ISREG(info.st_mode):
            return 'skipped', 'Source is no longer a regular file', None, None
        if info.st_size != row['bytes'] or int(info.st_mtime) != int(row['mtime']):
            return 'skipped', 'File changed since the preview', None, None
        target_dir = os.path.dirname(row['dst'])
        try:
            os.makedirs(target_dir, exist_ok=True)
            cross = op == 'move' and different_volume(info, target_dir)
        except OSError as exc:
            return 'failed', str(exc), None, None
        if cross:
            return self._cross_move(src, row['dst'], conflict, info)
        dst, n = row['dst'], 0
        while True:
            try:
                if op == 'move':
                    os.link(src, dst)
                else:
                    with open(src, 'rb') as a, open(dst, 'xb') as b:
                        shutil.copyfileobj(a, b)
                    shutil.copystat(src, dst)
                break
            except FileExistsError:
                if conflict == 'skip':
                    return 'skipped', 'A file with that name already exists', None, None
                n += 1
                dst = numbered(row['dst'], n)
            except OSError as exc:
                return 'failed', str(exc), None, None
        if op == 'move':
            try:
                os.unlink(src)
            except OSError as exc:
                return 'failed', f'Copied to destination but original could not be removed: {exc}', dst, info.st_ino
        return 'done', '', dst, os.lstat(dst).st_ino

    def _cross_move(self, src, dst_final, conflict, info):
        """Copy to a hidden temp file beside the target, verify by hash, commit without
        overwriting, then remove the original. The original is never removed unless the
        copy verified, and the temp file is always cleaned up."""
        tmp = os.path.join(os.path.dirname(dst_final), f'.sv-partial-{uuid.uuid4().hex[:8]}')
        try:
            digest = hashlib.sha256()
            with open(src, 'rb') as a, open(tmp, 'xb') as b:
                for chunk in iter(lambda: a.read(1 << 20), b''):
                    digest.update(chunk)
                    b.write(chunk)
                b.flush()
                os.fsync(b.fileno())
            shutil.copystat(src, tmp)
            if os.path.getsize(tmp) != info.st_size or _sha(tmp) != digest.hexdigest():
                return 'failed', 'Copy could not be verified; the original was left in place', None, None
            now = os.lstat(src)
            if now.st_size != info.st_size or int(now.st_mtime) != int(info.st_mtime):
                return 'skipped', 'File changed while it was being copied', None, None
            dst, n = dst_final, 0
            while True:
                try:
                    os.link(tmp, dst)
                    break
                except FileExistsError:
                    if conflict == 'skip':
                        return 'skipped', 'A file with that name already exists', None, None
                    n += 1
                    dst = numbered(dst_final, n)
            try:
                os.unlink(src)
            except OSError as exc:
                return 'failed', f'Copied and verified, but the original could not be removed: {exc}', dst, os.lstat(dst).st_ino
            return 'done', '', dst, os.lstat(dst).st_ino
        except OSError as exc:
            return 'failed', f'{exc}. The original was left in place', None, None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ---- crash recovery ----------------------------------------------
    def reconcile(self):
        """Settle ops left 'pending' by a crash by looking at the filesystem."""
        fixed = 0
        rows = self.journal.db.execute("SELECT batch,idx,kind,src,dst,size FROM ops WHERE status='pending'").fetchall()
        for batch, idx, kind, src, dst, size in rows:
            s_ok, d_ok = os.path.lexists(src), os.path.lexists(dst)
            for leftover in Path(dst).parent.glob('.sv-partial-*') if Path(dst).parent.is_dir() else []:
                try:
                    leftover.unlink()
                except OSError:
                    pass
            if kind == 'move' and s_ok and d_ok and not os.path.samefile(src, dst):
                try:
                    same = os.lstat(src).st_size == os.lstat(dst).st_size and _sha(src) == _sha(dst)
                except OSError:
                    same = False
                if same:
                    os.unlink(src)
                    self.journal.set_op(batch, idx, 'done', 'Recovered after interruption', ino=os.lstat(dst).st_ino)
                else:
                    self.journal.set_op(batch, idx, 'unknown', 'Both files exist and differ')
            elif kind == 'move' and s_ok and d_ok and os.path.samefile(src, dst):
                os.unlink(src)
                self.journal.set_op(batch, idx, 'done', 'Recovered after interruption', ino=os.lstat(dst).st_ino)
            elif kind == 'move' and d_ok and not s_ok:
                self.journal.set_op(batch, idx, 'done', 'Recovered after interruption', ino=os.lstat(dst).st_ino)
            elif s_ok and not d_ok:
                self.journal.set_op(batch, idx, 'failed', 'Interrupted before the change')
            elif kind == 'copy' and s_ok and d_ok:
                same = os.lstat(dst).st_size == size
                self.journal.set_op(batch, idx, 'unknown' if not same else 'done', 'Recovered after interruption')
            else:
                self.journal.set_op(batch, idx, 'unknown', 'Could not tell what happened')
            fixed += 1
        return fixed

    # ---- undo --------------------------------------------------------
    def undo(self, batch):
        results = {'undone': 0, 'skipped': 0}
        for op in reversed(self.journal.ops(batch)):
            if op['status'] != 'done':
                continue
            ok, detail = self._undo_one(op)
            self.journal.set_op(batch, op['idx'], 'undone' if ok else 'done', detail if not ok else 'Undone')
            results['undone' if ok else 'skipped'] += 1
            if not ok:
                results.setdefault('details', []).append(f"{op['dst']}: {detail}")
        return results

    def _undo_one(self, op):
        dst, src = op['dst'], op['src']
        try:
            info = os.lstat(dst)
        except OSError:
            return False, 'Moved file is no longer there'
        if not stat.S_ISREG(info.st_mode) or info.st_size != op['size'] or (op['ino'] and info.st_ino != op['ino']):
            return False, 'File has changed since it was moved'
        if op['kind'] == 'copy':
            try:
                self._trash(dst)
                return True, ''
            except Exception as exc:
                return False, str(exc)
        if os.path.lexists(src):
            return False, 'The original location is now occupied'
        try:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            if different_volume(info, os.path.dirname(src)):
                status, detail, _, _ = self._cross_move(dst, src, 'skip', info)
                return status == 'done', detail
            os.link(dst, src)
            os.unlink(dst)
            return True, ''
        except OSError as exc:
            return False, str(exc)
