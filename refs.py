"""Find local files that PowerPoint (.pptx) presentations link to instead of embedding.

Only external file relationships are read from the zip. Presentations that cannot be
read (encrypted, corrupt, oversized parts) are reported as unchecked, never as clean.
"""
import os
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

RELS = re.compile(r'^ppt/(slides|slideLayouts|slideMasters|notesSlides|notesMasters)/_rels/[^/]+\.rels$')
MAX_PART = 1_000_000
MAX_PRESENTATIONS = 500
WEB = ('http:', 'https:', 'mailto:', 'ftp:', 'tel:')


def key(path):
    return os.path.normpath(path).casefold()


def _target_path(target, base_dir):
    low = target.lower()
    if low.startswith(WEB):
        return None
    if low.startswith('file:'):
        local = unquote(urlparse(target).path)
        if len(local) > 2 and local[0] == '/' and local[2] == ':':
            local = local[1:]  # file:///C:/x -> C:/x
        return os.path.normpath(local)
    target = unquote(target)
    if target.startswith('/') or os.path.isabs(target):
        return os.path.normpath(target)
    return os.path.normpath(os.path.join(base_dir, target))


def presentation_links(path):
    """Return set of absolute linked file paths in one .pptx. Raises on unreadable files."""
    links = set()
    base = os.path.dirname(path)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not RELS.match(info.filename):
                continue
            if info.file_size > MAX_PART:
                raise ValueError('Relationship part too large')
            root = ET.fromstring(z.read(info))
            for rel in root:
                if rel.get('TargetMode') == 'External' and rel.get('Target'):
                    resolved = _target_path(rel.get('Target'), base)
                    if resolved:
                        links.add(resolved)
    return links


def scan_presentations(folders):
    refs, checked, unreadable, seen = {}, 0, [], set()
    for folder in folders:
        for current, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not d.endswith('.app')]
            for name in files:
                if not name.lower().endswith('.pptx') or name.startswith(('.', '~$')):
                    continue
                path = os.path.join(current, name)
                if path in seen:
                    continue
                seen.add(path)
                if len(seen) > MAX_PRESENTATIONS:
                    unreadable.append(path)
                    continue
                try:
                    links = presentation_links(path)
                    checked += 1
                    for link in links:
                        refs.setdefault(key(link), set()).add(path)
                except Exception:
                    unreadable.append(path)
    return {'refs': {k: sorted(v) for k, v in refs.items()}, 'checked': checked, 'unreadable': unreadable,
            'folders': list(folders)}


def wording(result):
    n = result['checked']
    base = f"No references found in the {n} checked presentation{'' if n == 1 else 's'}." if n else 'No presentations were checked.'
    if result['unreadable']:
        base += f" {len(result['unreadable'])} could not be checked, so their links are unknown."
    return base
