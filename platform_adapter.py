"""Everything that differs by operating system lives here. Shared code asks the adapter.

macOS is implemented and tested. The Windows adapter (drive letters, Recycle Bin,
AppData, system folder protection) is untested on real Windows hardware.
"""
import os
import shutil
import sys
from pathlib import Path

PROTECTED_EXT = {'.pem', '.key', '.p12', '.pfx', '.cer', '.crt', '.keychain', '.keychain-db',
                 '.mobileprovision', '.kext', '.plugin', '.component', '.vst', '.vst3', '.dylib'}
STANDARD = ('Desktop', 'Downloads', 'Documents', 'Pictures')


class PosixAdapter:
    name = 'posix'

    def app_support_dir(self):
        return Path.home() / '.local' / 'share' / 'StorageViewer'

    trash_name = 'Trash'
    trash_restore = 'Put Back in Finder'

    def roots(self):
        return ['/']

    def standard_folders(self):
        home = Path.home().resolve()
        return {n: str(home / n) for n in STANDARD}

    def volumes(self):
        u = shutil.disk_usage('/')
        return [{'mount': '/', 'total': u.total, 'used': u.used, 'free': u.free}]

    def protected_reason(self, path):
        if Path(path).suffix.lower() in PROTECTED_EXT:
            return 'Certificate, key or plugin file'
        return None

    def trash(self, path):
        from send2trash import send2trash
        send2trash(path)


class MacAdapter(PosixAdapter):
    name = 'macos'

    def app_support_dir(self):
        return Path.home() / 'Library' / 'Application Support' / 'StorageViewer'

    def volumes(self):
        out, seen = [], set()
        mounts = ['/'] + (sorted(str(p) for p in Path('/Volumes').iterdir()) if Path('/Volumes').is_dir() else [])
        for mount in mounts:
            try:
                dev = os.stat(mount).st_dev
                if dev in seen:
                    continue
                seen.add(dev)
                u = shutil.disk_usage(mount)
                out.append({'mount': mount, 'total': u.total, 'used': u.used, 'free': u.free})
            except OSError:
                pass
        return out

    def protected_reason(self, path):
        parts = Path(path).parts
        if any(part.endswith('.app') for part in parts):
            return 'Inside an application bundle'
        if 'Library' in parts:
            return 'Inside a Library folder'
        return super().protected_reason(path)


class WindowsAdapter(PosixAdapter):
    name = 'windows'
    trash_name = 'Recycle Bin'
    trash_restore = 'Restore in the Recycle Bin'
    SYSTEM_DIRS = ('windows', 'program files', 'program files (x86)', 'programdata', '$recycle.bin',
                   'system volume information', 'appdata')
    PROTECTED_EXT = PROTECTED_EXT | {'.sys', '.dll', '.msi', '.pfx', '.p7b'}

    def app_support_dir(self):
        base = os.environ.get('APPDATA') or str(Path.home() / 'AppData' / 'Roaming')
        return Path(base) / 'StorageViewer'

    def _drives(self):
        import string
        return [f'{c}:\\' for c in string.ascii_uppercase if os.path.exists(f'{c}:\\')]

    def roots(self):
        return self._drives()

    def volumes(self):
        out = []
        for drive in self._drives():
            try:
                u = shutil.disk_usage(drive)
                out.append({'mount': drive, 'total': u.total, 'used': u.used, 'free': u.free})
            except OSError:
                pass
        return out

    def protected_reason(self, path):
        parts = [p.lower() for p in Path(path).parts[1:]]
        if parts and parts[0] in self.SYSTEM_DIRS[:6]:
            return 'Windows system or program folder'
        if 'appdata' in parts:
            return 'Inside an AppData folder'
        if Path(path).suffix.lower() in self.PROTECTED_EXT:
            return 'Certificate, key, driver or installer file'
        return None


_ADAPTER = None


def get_adapter():
    global _ADAPTER
    if _ADAPTER is None:
        if sys.platform == 'darwin':
            _ADAPTER = MacAdapter()
        elif sys.platform == 'win32':
            _ADAPTER = WindowsAdapter()
        elif sys.platform.startswith('linux'):
            _ADAPTER = PosixAdapter()
        else:
            raise RuntimeError('Storage Viewer supports macOS and Windows only.')
    return _ADAPTER
