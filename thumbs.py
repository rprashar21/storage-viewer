"""Bounded image thumbnails via macOS sips. Reads only the selected image files."""
import base64
import os
import stat
import subprocess
import sys
import tempfile

IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.heic', '.tiff', '.webp', '.bmp'}
MAX_BYTES = 25_000_000
MAX_COUNT = 24
MAX_OUT = 80_000


def thumbnail(path, runner=subprocess.run):
    if os.path.splitext(path)[1].lower() not in IMAGE_EXT:
        return None
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
        return None
    if sys.platform != 'darwin' and runner is subprocess.run:
        return None  # thumbnails need macOS sips; Windows shows no preview
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 't.png')
        try:
            runner(['sips', '-Z', '96', '-s', 'format', 'png', path, '--out', out],
                   capture_output=True, timeout=5, check=True)
            if os.path.getsize(out) > MAX_OUT:
                return None
            with open(out, 'rb') as fh:
                return 'data:image/png;base64,' + base64.b64encode(fh.read()).decode()
        except (OSError, subprocess.SubprocessError):
            return None
