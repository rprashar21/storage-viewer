# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Read-only macOS desktop prototype that shows disk usage. Python backend (`scanner.py`, `app.py`) with a single-file HTML/CSS/JS frontend (`index.html`) hosted in a pywebview window. No frameworks, network server, database, or external assets. See `README.md` for measurement limits and permissions notes.

## Commands

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py                                   # run without packaging
.venv/bin/python -m unittest discover -s tests -v         # all tests
.venv/bin/python -m unittest tests.test_scanner.ScannerTests.<test_name>   # one test
bash build_macos.sh                                       # macOS only: venv, tests, PyInstaller -> dist/StorageViewer.app
```

`tests/ui_smoke.py` drives the real window and checks the DOM (macOS only): `.venv/bin/python tests/ui_smoke.py`. `sign_notarise_macos.sh` needs an Apple Developer ID and has never been run. Scanner tests run on Linux. The build script and the WebView need macOS. There is no linter configured.

## Architecture

- `app.py`: `Api` class is exposed to JS via pywebview (`overview`, `choose_folder`, `start_scan`, `scan_status`, `cancel_scan`). It owns the single-job lifecycle: a new scan is rejected until the previous one stops.
- `scanner.py`: `ScanJob` walks metadata iteratively in one background thread. It keeps only immediate-child rows, counters, and a bounded error sample (no full inventory, no caching). `snapshot()` returns a lock-protected consistent view that the UI polls.
- `platform_adapter.py`: every OS-specific piece (app data folder, volumes, protected paths, Trash, standard folders). Only macOS is implemented. Shared code must call `get_adapter()` rather than hard-code `~/Library` or macOS paths.
- `processes.py`: `ProcessSampler` (psutil). CPU is per-core scale; a process's first sample reports no CPU. Processes are keyed by pid plus create time.
- `findings.py`: `FindingsJob`, read-only cleanup candidates (large, old, installers, empty folders, exact duplicates). Duplicate detection is the only place file bytes are read.
- `cleanup.py`: `CleanupPlanner` moves reviewed candidates to the Trash (send2trash), two-step (`preview_cleanup` builds a single-use plan, `apply_cleanup` runs it). Only paths in the current findings are accepted. It blocks protected paths, never lets every copy of a duplicate group go, revalidates size/mtime per file, and logs to `~/Library/Application Support/StorageViewer/history.jsonl`. No permanent deletion.
- `organise.py`: builds a deterministic preview plan (presets, grouping, conflicts). `refs.py` reads external links from `.pptx` files so linked images default to Skip. `mover.py`: SQLite `Journal` plus `Mover` (link-then-unlink moves that never overwrite, crash `reconcile`, `undo`). `rules.py`: validated declarative saved rules. `watcher.py`: opt-in polling watcher (starts paused, suggest or auto, auto goes through `Mover`). `thumbs.py`: bounded thumbnails via `sips`. Cross-volume moves copy, hash-verify, then remove the original (`Mover._cross_move`). Journal and rules live in `~/Library/Application Support/StorageViewer/`.
- `index.html`: four tabs (Storage, Processes, Cleanup review, Organise). Storage polls `scan_status()` every 600 ms while scanning. Drill-down starts a fresh scan of the child folder. Back history lives only in memory in the page.

## Conventions to preserve

- Nothing changes on disk except through `cleanup.py` (Trash only) and `mover.py` (never overwrites, journalled, undoable), each after a confirmation step. File contents are read only for duplicate hashing in `findings.py`.
- Symlinks are skipped (and counted), not followed.
- Sizes are logical `st_size` bytes, not allocated bytes. Permission errors yield partial results, not failures.
- Progress is counts/time only, never an invented percentage.
- Tests use temporary directory fixtures and mock `os.scandir` for permission failures.
- Packaging bundles `index.html` via PyInstaller `--add-data`; new frontend assets must be added there too.
- `index.html` sets a strict CSP. pywebview's JS bridge needs `'unsafe-eval'` in `script-src`; without it `window.pywebview.api` never appears and the UI hangs on "Connecting to desktop app…".
