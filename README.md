# Storage Viewer — first feature

A local, read-only macOS desktop prototype. Plain HTML/CSS/JavaScript + Python.

## What is implemented

- Capacity, used and free space for the volume containing your home folder.
- Scan home, choose a folder, or scan the startup filesystem.
- Recursive logical file-size totals, largest-first rows, file counts and size bars.
- Folder drill-down (rescans that folder), Back, Rescan, progress and cancellation.
- Permission/error reporting with partial results and first 20 error details.
- Symlink skipping. Cleanup review moves reviewed items to the Trash and Organise moves or copies files, each only after an explicit confirmation and with no overwriting. No permanent deletion.

This is source code, not a prebuilt signed Mac app. Scanner checks run on Linux;
macOS permissions, native WebView, packaging and Gatekeeper are still to verify.

## Build on your Mac (developer only)

Use Python 3.11 or 3.12 installed from python.org or another trusted distribution.
Extract this folder, open Terminal here and run:

```bash
bash build_macos.sh
```

The script creates a development virtual environment, installs the pinned direct
requirements, runs tests, and builds `dist/StorageViewer.app`. It does not change
scanned files. Internet access is needed to install build dependencies. Transitive
dependencies are not yet locked; this is not a reproducible release pipeline.

Double-click that app. Its bundled Python runtime means end users do NOT need
Python, pip, a virtual environment, or Terminal. Build and test separately for
Apple Silicon and Intel before promising support for both. A native macOS build
cannot be produced by this Linux workspace.

For development without packaging:

```bash
.venv/bin/python app.py
```

For public distribution: choose your product bundle ID, sign the bundle with your
Apple Developer ID, notarise and staple the release, then distribute a DMG/ZIP.
The included script produces a local development build, not that public release.
Do not ask end users to disable Gatekeeper.

## Permissions and measurement limits

The app uses your account's normal permissions; it never requests root access.
If macOS blocks Desktop/Documents or other locations, results are partial.
Full Disk Access may be granted via System Settings > Privacy & Security after
installing the app, then quit/reopen/rescan. It does not bypass every protection.

Capacity is reported by `shutil.disk_usage(home)`. File rows sum `stat.st_size`:
logical bytes, NOT allocated physical bytes. Hard links count once per pathname;
APFS clones, snapshots, compression, sparse files and cloud placeholders differ
from physical usage. Metadata scans do not intentionally download cloud contents.

Startup filesystem scanning is exploratory: it may traverse mounted volumes and
macOS alternate/firmlink paths, so its totals can double-count storage. It is NOT
a complete physical-space reconciliation or an all-drives inventory. Use home
or explicit folders for the first validation. All-drive APFS-aware inventory is
a later milestone.

Filesystem changes during scanning are unavoidable. This is not an atomic
snapshot. Symlinks are skipped when inspected; hostile path-replacement races
are outside this prototype's guarantees. Folder sizes are observations at scan
time, not proof that files are unused or safe to delete.

## Architecture

`index.html` contains the interface and styles, no frameworks or external assets.
`app.py` creates the pywebview desktop window and exposes a narrow Python API.
`scanner.py` walks filesystem metadata in one background thread.
No network server, cloud, account, AI, database or continuously running service.

Flow:
1. Window initialises and calls `overview()` for capacity.
2. User chooses a scope. UI calls `start_scan(path)`.
3. Python validates the scope and starts one scan job.
4. UI calls `scan_status()` every 600 ms while scanning.
5. Scanner aggregates each immediate child's recursive size and file count.
6. UI displays sorted snapshots. Cancellation sets an event checked in traversal.
7. Drill-down starts a new scan; Back remembers only previous paths in memory.

The job stores immediate-child rows, counters and a bounded error sample. It does
not store a full inventory or cache previous scans. Progress is counts/time, not
an invented percentage: total work is unknown before traversal. Locks keep
snapshots consistent; new scans are rejected until the previous scan stops.

## Files

- `app.py`: window, bridge API and single-job lifecycle.
- `scanner.py`: iterative metadata scan and partial/cancelled states.
- `index.html`: dashboard and bridge polling.
- `requirements.txt`: runtime wrapper and packaging tool versions.
- `build_macos.sh`: Mac-only build instructions as a script.
- `tests/test_scanner.py`: scanner and API checks using temporary fixtures.

## Next validation on macOS

1. Build and open the app on a Mac without relying on system Python at runtime.
2. Scan a small fixture and check folder totals, then Desktop/Downloads.
3. Test macOS denied/granted permissions, cancellation, Back and Rescan.
4. Check UI responsiveness on a large folder and native folder picker behaviour.
5. Test a packaged app on a clean Mac, sign/notarise before public distribution.

Processes, cleanup, screenshot moves, undo and dependency checks are future
features. No cleaning actions are present in this release.

## Windows (untested)

A Windows adapter exists but has not been run on real Windows. Build on Windows 10/11 with
`powershell -ExecutionPolicy Bypass -File build_windows.ps1`, or run the `windows-build` GitHub
Actions workflow and download the zip. The result is unsigned, so SmartScreen will warn.
Known gaps: no image thumbnails, moves need NTFS (hard links), and system folders are blocked from cleanup.

### Organise inside a folder

Choose **Tidy Downloads** to preview loose files grouped into Images, Videos,
Documents, Audio, Archives and other type folders inside Downloads. Existing
folders stay intact. Select **View grouped by type** to browse without moving
anything, or **Move to another location** to choose a separate destination.
In-folder and view-only modes require one source and do not recurse. Unknown
file types go into Other; protected files remain blocked. Moves still require
review and confirmation, never overwrite, and use the existing History/undo.
Saved rules currently support only the separate-destination mode.
