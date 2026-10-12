# Release checklist: what still needs a person or other hardware

Status on 11 October 2026. Everything here is blocked on something outside this
workspace. Tick each item and paste any failure output back so it can be fixed.

## 1. Look at the app yourself (5 minutes)

1. Run `.venv/bin/python app.py` from this folder.
2. Storage tab: scan Downloads. Check the largest files, breadcrumbs and sort.
3. Cleanup review tab: review Downloads, tick one item, press "Review and move to Trash…", read the confirmation, cancel.
4. Organise tab: pick Screenshots, choose a destination, press Preview. Use COPIES of files first. Confirm, then undo from History.
5. Note anything confusing, slow or ugly. That list is the next round of work.

## 2. Clean-machine test (needs a second Mac)

1. Build here with `bash build_macos.sh`, then copy `dist/StorageViewer.zip` to a Mac with no Python or developer tools.
2. Check `dist/StorageViewer.zip.sha256` matches after copying.
3. Open the app. Expect a Gatekeeper warning until it is signed (item 3).
4. Confirm: capacity shows, a scan works, the Processes tab fills in, and a folder in Documents prompts for permission rather than failing silently.
5. Test both Apple Silicon and Intel if you plan to support both. This build is arm64 only.

## 3. Signing and notarising (needs an Apple Developer ID)

1. Join the Apple Developer Program and create a "Developer ID Application" certificate.
2. Run once: `xcrun notarytool store-credentials storage-viewer-profile`.
3. Run `DEVELOPER_ID="Developer ID Application: Your Name (TEAMID)" NOTARY_PROFILE=storage-viewer-profile bash sign_notarise_macos.sh`.
4. The script has never run, so expect to fix its first failure. Paste the output.
5. Decide the final bundle identifier. It is `com.storageviewer.desktop` today.

## 4. Windows (needs a Windows machine)

The platform layer exists in `platform_adapter.py`. A Windows adapter must supply:
drive letters and capacity, the standard folders, the app data folder (AppData),
Recycle Bin handling, protected locations (Program Files, Windows, AppData),
junction and reparse point handling in `scanner.py`, and long path support. Then
package with PyInstaller on Windows and test without Python installed. Do not
register it in `get_adapter()` until it has been tested there.

## 5. Payments (decision needed)

Deferred by `features.md`. Before any code: choose free versus paid features,
one-time versus subscription, and a hosted checkout provider. Purchases must be
verified on a backend, and no payment secrets may ship inside the app.
`PRODUCT.md` suggests validating with a few real users first.
