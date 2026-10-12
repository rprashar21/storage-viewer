"""User-kept list of paths that cleanup reviews must never report."""
import json
import os
from pathlib import Path

from platform_adapter import get_adapter

DEFAULT_PATH = get_adapter().app_support_dir() / 'ignored.json'


class IgnoreStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    def list(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return [p for p in data if isinstance(p, str) and os.path.isabs(p)]
        except (OSError, ValueError):
            return []

    def _write(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(set(items))), encoding='utf-8')

    def add(self, path):
        if not isinstance(path, str) or not os.path.isabs(path) or os.path.dirname(path) == path:
            raise ValueError('Choose a specific folder or file')
        self._write(self.list() + [os.path.normpath(path)])

    def remove(self, path):
        self._write([p for p in self.list() if p != path])


def is_ignored(path, ignored):
    return any(path == p or path.startswith(p + os.sep) for p in ignored)
