"""Deterministic organisation preview. Builds a plan; never touches files."""
import hashlib
import os
import re
import stat
import time
from pathlib import Path

from cleanup import protected_reason
from refs import key as ref_key
from scanner import EXT_CATEGORY

RULE_VERSION = 1
PRESETS = {'screenshots', 'images', 'documents', 'videos', 'archives', 'by_type'}
GROUPS = {'none', 'year', 'month'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.heic', '.gif', '.tiff', '.webp'}
SCREENSHOT = re.compile(r'^(screenshot|screen shot)\b', re.I)
PRESET_CATEGORY = {'images': 'Images', 'documents': 'Documents', 'videos': 'Video', 'archives': 'Archives'}
MAX_ROWS = 2000


def match_rule(name, preset):
    """Return (category, reason) or None. PNG alone is never treated as a screenshot."""
    ext = os.path.splitext(name)[1].lower()
    category = EXT_CATEGORY.get(ext, 'Other')
    if preset == 'screenshots':
        if ext in IMAGE_EXT and SCREENSHOT.match(name):
            return category, 'Name looks like a macOS screenshot'
        return None
    if preset == 'by_type':
        return (category, f'Grouped by type: {category}') if category != 'Other' else None
    wanted = PRESET_CATEGORY[preset]
    return (category, f'{wanted} by file extension') if category == wanted else None


def _dest_dir(dest, category, preset, group_by, mtime):
    parts = [dest]
    if preset == 'by_type':
        parts.append(category)
    t = time.localtime(mtime)
    if group_by == 'year':
        parts.append(f'{t.tm_year}')
    elif group_by == 'month':
        parts.append(f'{t.tm_year}-{t.tm_mon:02d}')
    return os.path.join(*parts)


def _walk(source, dest, recursive):
    dest_key = os.path.normpath(dest)
    stack = [source]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith('.'):
                continue
            try:
                info = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                full = os.path.normpath(e.path)
                if recursive and not e.name.endswith('.app') and full != dest_key and e.name != 'Library':
                    stack.append(e.path)
            elif stat.S_ISREG(info.st_mode):
                yield e.path, info


def _nearest_dev(path):
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return os.stat(p).st_dev


def build_plan(sources, dest, preset, group_by='none', recursive=False, conflict='rename', ref_index=None):
    if preset not in PRESETS or group_by not in GROUPS or conflict not in ('rename', 'skip'):
        raise ValueError('Unknown option')
    dest = os.path.normpath(dest)
    dest_dev = _nearest_dev(dest)
    refs = (ref_index or {}).get('refs', {})
    rows, claimed = [], set()
    for source in sources:
        source = os.path.normpath(source)
        if source == dest:
            raise ValueError('Destination cannot be a source folder')
        for path, info in _walk(source, dest, recursive):
            if len(rows) >= MAX_ROWS:
                break
            if path.startswith(dest + os.sep):
                continue
            hit = match_rule(os.path.basename(path), preset)
            if not hit:
                continue
            category, reason = hit
            target_dir = _dest_dir(dest, category, preset, group_by, info.st_mtime)
            target = os.path.join(target_dir, os.path.basename(path))
            row = {'src': path, 'dst': target, 'category': category, 'rule': preset, 'reason': reason,
                   'bytes': info.st_size, 'mtime': info.st_mtime, 'status': 'ready', 'warnings': [],
                   'selected': True, 'op': 'move', 'referenced_by': [], 'conflict': conflict}
            blocked = protected_reason(path)
            if blocked:
                row.update(status='blocked', selected=False, warnings=[blocked])
            elif info.st_dev != dest_dev:
                row['warnings'].append('Different volume: copied, verified, then the original is removed')
            elif target in claimed or os.path.lexists(target):
                row['warnings'].append('A file with this name exists or is also planned: ' +
                                       ('it will be skipped' if conflict == 'skip' else 'a numbered name will be used'))
            claimed.add(target)
            linked = refs.get(ref_key(path))
            if linked and row['status'] == 'ready':
                row.update(op='skip', selected=False, referenced_by=linked,
                           warnings=row['warnings'] + ['Linked from a presentation. Skipped by default; you can copy instead.'])
            rows.append(row)
    rows.sort(key=lambda r: (r['src'].casefold()))
    digest = hashlib.sha256()
    digest.update(f'{RULE_VERSION}|{preset}|{group_by}|{recursive}|{conflict}|{dest}'.encode())
    for r in rows:
        digest.update(f"|{r['src']}|{r['dst']}|{r['bytes']}|{int(r['mtime'])}|{r['status']}".encode())
    return {'id': digest.hexdigest()[:16], 'rule_version': RULE_VERSION, 'preset': preset, 'group_by': group_by,
            'recursive': recursive, 'conflict': conflict, 'dest': dest, 'sources': list(sources), 'rows': rows,
            'ready': sum(r['status'] == 'ready' for r in rows), 'blocked': sum(r['status'] == 'blocked' for r in rows),
            'linked': sum(bool(r['referenced_by']) for r in rows),
            'capped': len(rows) >= MAX_ROWS,
            'presentations': ({'checked': ref_index['checked'], 'unreadable': len(ref_index['unreadable']),
                               'folders': ref_index['folders']} if ref_index else None)}
