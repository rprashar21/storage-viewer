"""Move reviewed cleanup candidates to the Trash. Never permanent delete, never overwrite.

Only paths present in the current findings snapshot are accepted. Every item is
revalidated against the size/mtime that was measured when the finding was made.
"""
import json
import os
import stat
import time
import uuid
from pathlib import Path

from platform_adapter import get_adapter

DEFAULT_LOG = get_adapter().app_support_dir() / 'history.jsonl'


def protected_reason(path):
    return get_adapter().protected_reason(path)


DERIVED_MARK = '/Library/Developer/Xcode/DerivedData/'


class CleanupPlanner:
    def __init__(self, trash=None, log_path=DEFAULT_LOG):
        if trash is None:
            trash = get_adapter().trash
        self._trash, self._log, self._plans = trash, Path(log_path), {}

    def build(self, snapshot, paths):
        known, groups = {}, []
        for f in snapshot['findings']:
            for item in f['items']:
                known.setdefault(item['path'], (f['rule'], item))
            if f['rule'] == 'duplicates':
                groups = f.get('groups', [])
        selected = set(paths)
        items = []
        for path in dict.fromkeys(paths):
            entry = known.get(path)
            if not entry:
                items.append(self._row(path, '?', 0, None, 'blocked', 'Not part of the current review'))
                continue
            rule, info = entry
            reason = protected_reason(path)
            if reason and rule == 'dev' and DERIVED_MARK in path:
                reason = None  # Xcode DerivedData lives in Library but is rebuilt by Xcode
            if reason:
                items.append(self._row(path, rule, info['bytes'], info['mtime'], 'blocked', reason))
            elif path == snapshot['path']:
                items.append(self._row(path, rule, 0, None, 'blocked', 'The reviewed folder itself'))
            else:
                items.append(self._row(path, rule, info['bytes'], info['mtime'], 'ready', ''))
        for members in groups:
            if members and all(m in selected for m in members):
                for row in items:
                    if row['path'] in members and row['status'] == 'ready':
                        row['status'], row['reason'] = 'blocked', 'This would remove every copy'
        plan = {'id': uuid.uuid4().hex, 'items': items, 'groups': groups,
                'count': sum(r['status'] == 'ready' for r in items),
                'bytes': sum(r['bytes'] for r in items if r['status'] == 'ready'),
                'blocked': sum(r['status'] == 'blocked' for r in items)}
        self._plans[plan['id']] = plan
        return plan

    @staticmethod
    def _row(path, rule, size, mtime, status, reason):
        return {'path': path, 'rule': rule, 'bytes': size, 'mtime': mtime, 'status': status, 'reason': reason}

    def apply(self, plan_id):
        plan = self._plans.pop(plan_id, None)
        if plan is None:
            raise ValueError('This confirmation expired. Review the selection again.')
        trashed = set()
        results = []
        for row in plan['items']:
            if row['status'] != 'ready':
                results.append({'path': row['path'], 'outcome': 'skipped', 'detail': row['reason']})
                continue
            problem = self._changed(row, plan['groups'], trashed)
            if problem:
                results.append({'path': row['path'], 'outcome': 'skipped', 'detail': problem})
                continue
            try:
                self._trash(row['path'])
                trashed.add(row['path'])
                results.append({'path': row['path'], 'outcome': 'trashed', 'bytes': row['bytes'], 'detail': ''})
            except Exception as exc:
                results.append({'path': row['path'], 'outcome': 'failed', 'detail': str(exc)})
        summary = {'at': time.time(), 'trashed': sum(r['outcome'] == 'trashed' for r in results),
                   'bytes': sum(r.get('bytes', 0) for r in results if r['outcome'] == 'trashed'),
                   'results': results}
        self._write_log(summary)
        return summary

    @staticmethod
    def _changed(row, groups, trashed):
        try:
            info = os.lstat(row['path'])
        except OSError:
            return 'No longer exists'
        if stat.S_ISLNK(info.st_mode):
            return 'Is now a link'
        if row['rule'] == 'dev':
            if not stat.S_ISDIR(info.st_mode):
                return 'No longer a folder'
        elif row['rule'] == 'empty':
            if not stat.S_ISDIR(info.st_mode) or os.listdir(row['path']):
                return 'Folder is no longer empty'
        else:
            if not stat.S_ISREG(info.st_mode) or info.st_size != row['bytes'] or int(info.st_mtime) != int(row['mtime']):
                return 'File changed since the review'
        for members in groups:
            if row['path'] in members and not any(m != row['path'] and m not in trashed and os.path.exists(m)
                                                  for m in members):
                return 'No other copy remains'
        return None

    def _write_log(self, summary):
        try:
            self._log.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(summary) + '\n')
        except OSError:
            pass
