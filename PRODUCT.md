# Product notes: is it sellable?

Internal assessment, 11 October 2026. Competitor comparisons come from general
knowledge of the Mac utility market, not from research done in this project.
Nothing here is validated with real users yet.

## Business problem

A Mac fills up. The owner can't see what is using the space, doesn't trust
tools that offer to "clean" without saying why, and is afraid to delete the
wrong thing. They also can't tell whether the machine is slow because of
storage or because of a runaway process.

## What we offer that is hard to copy

Trust. Everything is local and read-only until the user confirms. Each cleanup
suggestion states the reason and its limits ("old does not mean unused"). The
app never deletes permanently, never removes every copy of a duplicate, skips
certificates, keys, plugins, Library and app bundles, and re-checks each file
immediately before moving it to the Trash. No account, cloud or telemetry.

## Feature-by-feature verdict

| Feature | Sellable alone? | Why |
| --- | --- | --- |
| Folder explorer, largest files, type breakdown | No | Expected. macOS Storage settings and free tools cover it. DaisyDisk wins on visuals. |
| Volumes and one-volume scans | No | Hygiene that keeps totals honest. |
| Processes tab | No | Duplicates Activity Monitor. Only useful next to storage. |
| Cleanup review (large, old, installers, empty, exact duplicates) | Yes, the core | Gives reasons and limits where competitors give a "clean" button. |
| Confirmed move to Trash with safeguards | Yes | Safety is the reason people would pay instead of using a free analyser. |

## Sellability check per feature (done as each was built)

- **Organise preview (Desktop, Downloads, screenshots).** Sellable. People
  already use Hazel-style rules, but those apply changes with little preview.
  Ours shows every source, destination and reason first, with one-tap
  "Pictures/Screenshots". Weak spot: no thumbnails yet, so users judge by file
  name. Add bounded thumbnails for selected images before charging.
- **PowerPoint link warnings.** The strongest differentiator in this set.
  Moving a linked image silently breaks a deck, and few organisers warn about
  it. The warning is honest: it says how many presentations were checked and how
  many could not be read. Limits: .pptx only, and only presentations inside
  Documents, Desktop, Downloads and the chosen sources.
- **Journalled moves with undo.** Sellable as the trust feature that makes
  organising safe to try. Moves never overwrite, are re-checked just before
  running, and survive a crash through a journal. Limits: same volume only,
  undo refuses if the file changed or the old path is occupied.
- **Saved rules, export and import.** Useful for repeat use and for sharing a
  setup with a team. Imports are validated data only and never run code. The
  opt-in background watcher is not built, so there is no "set and forget" yet.
  That is a real gap against Hazel.
- **Thumbnails in the preview.** Sellable detail. Users judge screenshots by
  looking, not by file name, so this removes the main weakness found in the
  organise preview. Bounded: 24 images, 25 MB each, via the built-in macOS
  `sips`, with no new dependency.
- **Cross-volume moves.** Needed for external drives and a second disk, which is
  where many large libraries live. Copy, verify by hash, then remove the original,
  and the original is never touched if verification fails. Checked with simulated
  volumes, disk-full and interruption tests, but not yet on a real external drive.
- **Background watcher.** Closes the biggest gap against Hazel-style tools.
  Opt-in, starts paused, suggest mode by default, auto mode needs a confirmation,
  waits for files to stop changing, skips partial downloads and linked
  presentation files, and every automatic batch can be undone. Limit: it runs only
  while the app is open, so it is not yet a true background service.
- **Signing script.** Not a feature users see, but the gate to selling.
  `sign_notarise_macos.sh` is written and syntax-checked but has never run,
  because it needs an Apple Developer ID.
- **Developer build clutter** (checked right after building it). Sellable, and
  the best wedge found so far. Developers hit full disks because of
  `node_modules`, Pods, Rust `target` and Xcode DerivedData, and generic
  cleaners either miss them or delete them blindly. Ours only flags a folder
  when its project manifest is beside it, lists size per project, says what
  recreating costs, and moves to the Trash behind the same confirmation.
  Limits: four tool types only, sizes are logical bytes, and no Docker,
  Gradle, simulators or Homebrew caches yet. A developer audience also needs
  a way to exclude folders they are mid-build in.
- **Platform adapter.** Not user-visible. Windows is the next market, and this keeps
  the shared scanner, rules and UI reusable. It only becomes sellable once a
  tested Windows adapter exists.
- **Earlier features** are judged in the table above.

## Gaps before charging money

1. A visual view (treemap or sunburst). Without it the product looks plain next to DaisyDisk.
2. More developer and creative junk. node_modules, Pods, Rust target and DerivedData are covered. Docker data, Gradle, Homebrew caches and old simulators are not. This is where full disks usually come from for the most willing-to-pay users. It is also where "safe to remove" needs the most care.
3. First-run Full Disk Access guidance, so scans of protected folders are not silently partial.
4. Speed on a large drive, measured on a real Mac.
5. Developer ID signing and notarisation, so it opens without Gatekeeper warnings.
6. Undo for Trash cleanups. Organise moves have in-app undo. Cleanup uses Finder's Put Back, and space is freed only when the Trash is emptied.
7. A watcher that keeps running when the app window is closed (a login item). Today it runs only while the app is open.
8. Windows support and a payment flow, which depend on a Windows machine and your pricing decision.

## Suggested wedge

Target developers and creatives with full disks first. They feel the pain,
understand the risk of deleting the wrong thing, and value a tool that shows
its reasoning. Validate with a handful of real users before pricing.
