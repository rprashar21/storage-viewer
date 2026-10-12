# Storage Viewer: product roadmap and Claude Code handoff

Updated: 11 October 2026. Read this before changing the source.

## 1. Owner's goal and settled decisions

Build a downloadable desktop application for ordinary users to:
- Understand storage across their computer, drives, folders and files.
- Drill down: drive -> Desktop (e.g. 50 GB) -> ten folders with sizes -> files.
- See running processes and their CPU/memory consumption in another tab.
- Review possible cleanup opportunities with reasons and limitations.
- Organise scattered screenshots, Desktop and Downloads into chosen destinations.
- Protect certificates, plugins, project assets and linked document resources.

Start on macOS: the owner's laptop is a Mac. Windows follows later.
Use Python and plain HTML/CSS/JavaScript. No React, TypeScript, Tauri or Rust
unless a concrete problem justifies proposing a change to the owner.
No AI, LLM calls, embeddings or cloud classification. Rules are deterministic.
Ship one useful feature at a time. Keep the implementation small.
End users must not install Python, pip, or use Terminal. The packaged desktop
app includes the Python runtime. Developer setup is separate from user setup.
Future paid features/payment gateway are deferred; no accounts or billing now.

## 2. What already exists — accurate status

Source archive: `storage-viewer-v0.1-source.zip`. Extract to obtain `storage-viewer/`.
This is a source prototype, NOT a shipped binary or tested macOS release.
No GitHub repository, signing identity, deployment or public download exists.

Implemented:
- Desktop entry point with pywebview and a locally loaded HTML interface.
- Capacity/used/free for the volume containing the user's home directory.
- Scan home, native folder chooser, and exploratory startup filesystem scan.
- Recursive logical file sizes grouped by immediate child folder/file.
- Largest-first rows, file counts, proportional size bars and current scan path.
- Background thread; status polling every 600 milliseconds.
- Cancellation; one scan at a time; elapsed time and counts rather than fake %.
- Folder drill-down by rescanning; Back stores prior paths; Rescan.
- Permission/error reporting; partial/cancelled/failed scan states.
- First 20 error details; full error count; symlink count and skipping.
- No file mutations and no image/document-content reads.
- Mac-only packaging script intended to produce `dist/StorageViewer.app`.

Verified in a Linux workspace:
- Five stdlib unit tests pass: nested sizes/empty folders/symlink loops;
  permission denial; pre-cancelled scan; missing root/snapshot isolation;
  rejecting an unselected API path.
- Python compilation succeeds.
- JavaScript syntax check succeeds.
- Build script shell syntax check succeeds.

NOT verified:
- Native Mac window, folder picker and macOS permissions.
- Actual packaged app, frozen asset lookup, bundle dependencies or clean-Mac use.
- Visual layout and browser interactions: attempted Playwright check could not
  launch because this workspace had no Chromium executable.
- Large-drive performance, Apple Silicon/Intel compatibility, signing/notarisation.

NOT implemented:
All-drive inventory, APFS-aware physical reconciliation, processes, cleanup,
organisation/moves/copies, undo, thumbnails, duplicate detection, dependency
checking, saved rules, background watching, updates, Windows, payments.

## 3. Current architecture and code map

One desktop process, one background scanner thread. No HTTP service, database,
cloud service, telemetry, persistent inventory or full file-content index.

| File | Responsibility |
| --- | --- |
| `app.py` | Window creation; Python bridge; path scopes; single-job lifecycle |
| `scanner.py` | ScanJob; iterative traversal; logical size aggregation; snapshots |
| `index.html` | HTML, CSS, JS controls, rendering and status polling |
| `requirements.txt` | pywebview 6.2.1; PyInstaller 6.22.0 |
| `build_macos.sh` | Creates venv, installs deps, runs tests, packages app |
| `tests/test_scanner.py` | Five temporary-fixture/API tests |
| `README.md` | Current build instructions and measurement limitations |

Runtime sequence:
1. `main()` loads bundled index.html and creates a pywebview window.
2. JS waits for `pywebviewready`, then calls `overview()`.
3. A scan button calls `start_scan(path)`.
4. Api validates the selected scope and starts ScanJob.run in a daemon thread.
5. Scanner uses os.scandir and stat(follow_symlinks=False).
6. Folder traversal is iterative; each child gets a recursive logical byte total.
7. JS calls scan_status every 600 ms while scanning; snapshots are lock-protected.
8. cancel_scan sets an Event; traversal checks it between entries/directories.
9. Clicking a folder starts a fresh scan. No cached drill-down inventory yet.

Bridge methods: overview, choose_folder, start_scan, scan_status, cancel_scan.
Only the home path, `/`, chosen paths and discovered child folders are accepted.
This is a read-only scope check, not a security boundary against hostile local
filesystem changes. UI uses textContent for filenames, not HTML interpolation.

## 4. Measurement semantics and known limitations

- Volume figures use shutil.disk_usage(home); not an inventory of every drive.
- Folder totals sum st_size (logical bytes), not allocated physical bytes.
- Hard links count per pathname; snapshots/clones/compression/sparse files and
  cloud placeholders can make these figures differ from physical disk usage.
- The `/` button is exploratory. macOS firmlinks/alternate paths and mount points
  can cause duplicate traversal and include other volumes. Do not call it an
  accurate whole-computer storage total. Fix scope traversal before that claim.
- Top-level rows appear as each child is reached; a huge first child can delay
  discovery of the rest. Child discovery/progress fairness is worth improving.
- Permission errors mean incomplete coverage, not zero usage.
- Source files can change during scanning; this is not an atomic snapshot.
- Cancellation is cooperative: a blocking filesystem call can delay it.
- Traversal stacks and all immediate-child rows are not strictly memory-bounded.
  Large directories need pagination/virtualisation and batching when justified.
- Snapshot elapsed currently keeps increasing after completion. Freeze end time.
- A top-level metadata failure creates only a global error, no visible item row.
  Consider an unavailable row so users see which item is missing.
- Resolve/path checks and skip-symlink metadata checks do not eliminate path
  replacement races. Review carefully before enabling writes.
- Builds pin direct dependencies, not the complete transitive dependency tree.
- Public Mac distribution is still unsigned/unnotarised and unsupported.

## 5. Roadmap — implement sequentially

### Milestone 0 — validate the existing Mac prototype (NEXT TASK)

Goal: double-clickable local development app on the owner's Mac.
- Read current files and preserve the stack/behaviour.
- Confirm installed Python version, macOS version and CPU architecture locally.
- Run tests, install build dependencies in an isolated venv, build the .app.
- Validate native window, JS bridge, file picker and bundled HTML lookup.
- Scan known-size fixtures; test drill-down, Back, Rescan, cancellation.
- Test denied/granted folder permissions and report errors honestly.
- Freeze completed elapsed time; correct concrete lifecycle/UI defects found.
- Do not add unrelated features while resolving packaging.

Done: local packaged app works; record exact Mac/version/architecture and checks.
Public distribution is a separate gate. Developer installation of Python is OK;
requiring end users to install it is not.

### Milestone 1 — complete the storage explorer

Goal: whole-computer overview with scoped, honest drive/folder drill-down.
- Enumerate supported local/external volumes; display capacity/used/free per volume.
- Define APFS container sharing and mount/firmlink handling explicitly.
- Default to local user data; distinguish system/app/user/external locations.
- Show Desktop, Downloads, Documents, Pictures, Library and Applications when
  accessible, with useful navigation; mark aliases as overlapping views.
- Avoid counting Desktop/Downloads again in a grand total already containing them.
- Control cross-volume traversal; scan each chosen scope intentionally.
- List immediate children promptly, then populate totals progressively.
- Add path breadcrumbs, sort controls, largest-file view and type breakdown.
- Show scanned timestamp, coverage, inaccessible areas and skipped links.
- Validate responsiveness, memory use, long paths and huge folders on real Macs.
- Add caching/pagination only when measurements justify it; no database by default.

Done: locate Downloads at 100 GB, drill into it, identify the biggest files;
volume capacity and scanned totals remain clearly differentiated.

### Milestone 2 — processes tab

Goal: resource visibility, not unproven claims about what slows the laptop.
- Add psutil after validating its macOS behaviour/version.
- Overall CPU/RAM and process name, PID, CPU%, memory and availability state.
- Define CPU normalisation: total-machine scale or per-core; label consistently.
- Sample deltas over time; do not show an uninitialised first CPU sample as truth.
- Sort by resource usage; short recent history; pause sampling when appropriate.
- Handle process exit, permission denial and PID reuse (PID + creation time).
- Limit polling overhead; test against Activity Monitor with documented differences.
- I/O metrics later; no process termination controls initially.

Done: user sees which processes consume resources and how recently measured.
High CPU consumption alone does not prove harmful behaviour.

### Milestone 3 — cleanup findings, read-only first

Goal: evidence-based review candidates with meaningful space estimates.
- Large Downloads files; old modified files; old installers/archives; empty folders.
- Exact duplicates: group by size, hash candidates, verify byte equality as needed;
  compare identity/change metadata so stale hashes do not authorise actions.
- Recycle Bin/Trash and named supported temp/cache locations.
- Rules return reason, affected files, measurement time, coverage and protection.
- Separate large, old, duplicate and supported-cache classifications.
- Never say old == unused, duplicate == unnecessary, or no open handle == safe.
- Recoverable space must account for links/clones/selected retained copies or be
  labelled an estimate; organising on the same volume frees no storage.
- No general Library/application/plugin/certificate deletion.

Done: user can understand and inspect each finding; no deletion yet.

### Milestone 4 — organisation preview

Goal: user-selected folders/destination and deterministic proposed operations.
- First preset: collect screenshots from chosen sources into chosen destination.
- Filename conventions + recognised image formats/known screenshot locations;
  PNG alone does not identify a screenshot. Renamed screenshots may be missed.
- Show thumbnails only for selected supported image candidates; bounded reads.
- Desktop/Downloads presets: images, documents, videos, archives.
- Other grouping: extension/category, filename pattern, selected date/year/month.
- Existing subfolders stay intact by default; recursion is an explicit choice.
- Exclude application bundles, projects, certificates/keys, plugins and config assets.
- Every plan row: source, destination, rule/reason, source fingerprint, warnings,
  user selection, conflict policy, plan ID and rule version.
- Exclude destinations from source matching; prevent moving folders into themselves.
- Preview makes no changes. User chooses precisely which rows to approve.

Done: consistent plan for the same snapshot/rules; no file modifications.

### Milestone 5 — dependency warnings before general moves

Goal: identify supported known references, disclose everything not checked.
- Begin with .pptx external file relationships in user-selected document folders.
- Resolve relative paths and local file URIs; handle case/path identity and errors.
- Distinguish embedded images (self-contained copy) from linked external images.
- A known link defaults to Skip and offers Copy instead; preserve original path.
- Warning identifies the referring presentation and the proposed affected file.
- Unsupported/encrypted/corrupt documents and out-of-scope references are unknown.
- Use wording: 'No references found in the 24 checked presentations.' Never
  'No applications depend on this file' or 'Definitely safe to move/delete'.
- Embedded-image byte equality does not prove original provenance, especially
  after recompression. Do not promise universal 'image used in PPT' detection.
- Later adapters: supported Word/Excel/HTML/playlist links, where useful.
- Do not rewrite presentations or app configs automatically in the first release.

Done: linked-image fixtures warn accurately; scope and unknowns are visible.

### Milestone 6 — controlled moves/copies and undo

Goal: first writing feature with recovery built in.
- Start with same-volume file moves inside user-approved scopes.
- Revalidate source fingerprint, destination and reference checks before execution.
- Never overwrite; explicit skip/rename conflict policies.
- Write durable operation journal before each mutation and outcome afterward.
- Per-file states for pending/succeeded/failed/unknown; report partial batches.
- Crash recovery reconciles journal and filesystem rather than guessing success.
- Undo verifies file identity/state and original path availability; no overwriting.
- SQLite or another durable transactional journal becomes justified HERE.
- Preserve protected assets and linked files unless individually reviewed.
- Later cross-volume move: copy to temporary destination, verify, commit, remove
  original only when validated; test interruption and disk-full failures.

Done: preview -> apply selected moves -> history -> safe undo, including failures.

### Milestone 7 — controlled cleanup actions

- Build on the reviewed plan/executor/history mechanisms.
- Prefer Trash over permanent deletion; show consequences before execution.
- Native supported cleanup paths; no blanket recursive cache deletion.
- Respect application-owned data and actively changing files.
- Show actual outcomes; distinguish recoverable estimates from measured freed space.
- Native Trash restore and emptied-Trash limitations must be explained accurately.

Done: fixture-based and manual tests show cleanup cannot silently overwrite or
remove protected/unreviewed files. Permanent-delete mode remains deferred.

### Milestone 8 — saved rules and optional automation

- Save/export/import validated declarative rules and presets.
- Define rule priority, conflicts, exclusions and rule versions.
- Restrict actions: do not import executable Python/shell rules from other tools.
- Background watchers only as opt-in; wait for download completion/stable files.
- Ignore destination folders; prevent loops; debounce events and cap work.
- Preview/manual runs remain available; logs and pause controls always visible.

### Milestone 9 — public macOS release

- Choose app identity/name/icon, supported macOS versions and CPU architectures.
- Test clean machines without Python installed, permissions and offline startup.
- Lock release dependencies, document third-party licences, sign with Developer ID.
- Notarise/staple; package DMG/ZIP; provide versioned downloads and checksums.
- Add graceful failure messages and user-controlled diagnostics without exposing
  private paths unnecessarily; never introduce telemetry without a clear decision.
- Signed update mechanism after reliable manual distribution, not before.

A read-only public beta may ship after storage validation; writing features need
their own gates. 'Public release' is not permission to publish without owner scope.

### Milestone 10 — Windows support

- Keep shared UI/rules/scanner; isolate Windows-specific adapters.
- Drive discovery, junctions/reparse points, long paths, permissions, hard links,
  process sampling, Trash semantics and installer/signing.
- Build/package on Windows; test without Python installed.
- Protect certificate stores, Program Files, AppData, plugins and project assets.

### Milestone 11 — monetisation (deferred)

- Validate repeated user value before deciding free vs paid features.
- Discuss one-time licence/subscription with owner; no price decisions yet.
- Payment through hosted provider checkout; verify purchases on a backend.
- Signed entitlement/licence, offline policy, refunds, recovery and update access.
- Never embed payment secrets in a desktop binary or trust a client success screen.

## 6. Reuse research to retain

References, not dependencies currently installed:
- https://github.com/tfeldmann/organize : Python rule engine; MIT; simulation,
  filters/actions/conflicts. Evaluate selectively; unrestricted scripts/actions
  must not bypass our preview, protection checks or future journal.
- https://www.noodlesoft.com/ : Hazel rule previews and matching explanations.
- https://www.filejuggler.com/ : folder rules and monitoring interaction ideas.
- https://www.dropitproject.com/ : profiles/ignore rules; old AutoIt project,
  not chosen as backend.
- https://diskanalyzer.com/ : WizTree storage UX; not a free reusable source engine.
- https://github.com/windirstat/windirstat : storage UX/design; current repo GPL,
  do not copy source into a proprietary product without checking obligations.

The existing scanner is custom stdlib Python. No dependency engine or organiser
has already been integrated. Verify exact licences/versions before incorporation.

## 7. Development instructions for Claude Code

1. Treat this source as the starting point. Read README and files; do not rewrite
   the project or introduce a framework to make it look more complete.
2. Owner wants small, reviewable increments. Work on Milestone 0 first.
3. Run `python3 -m unittest discover -s tests -v` from storage-viewer/.
4. On Mac, run `bash build_macos.sh`; inspect failures and frozen execution.
5. Add meaningful tests for new behaviour; do not claim Mac tests ran elsewhere.
6. Record scope, changed files, validation and remaining limitations per milestone.
7. Explain dependency additions and technical trade-offs to the owner plainly.
8. Do not add accounts, billing, AI, process-killing, permanent deletion or
   unrestricted script execution while implementing storage.
9. Once this is in a repo, follow AGENTS.md and the owner's existing workflow.

First assignment:
'Validate and repair the packaged macOS Storage Viewer prototype. Preserve plain
HTML/CSS/JS + Python + pywebview. Make scanning, progress, cancellation, folder
picker, drill-down and Back work in the .app. Freeze finished elapsed time. Test
permission failures and known-size fixtures. Report exact checks, platform and
remaining limitations. Do not implement later roadmap features yet.'
