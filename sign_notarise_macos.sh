#!/bin/bash
# Sign, notarise and package dist/StorageViewer.app. UNTESTED: needs an Apple Developer ID.
# Usage: DEVELOPER_ID="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=profile-name bash sign_notarise_macos.sh
# Create the profile once with: xcrun notarytool store-credentials profile-name
set -euo pipefail
cd "$(dirname "$0")"
: "${DEVELOPER_ID:?Set DEVELOPER_ID to your Developer ID Application identity}"
: "${NOTARY_PROFILE:?Set NOTARY_PROFILE to a notarytool keychain profile}"
APP=dist/StorageViewer.app
codesign --force --deep --options runtime --timestamp --sign "$DEVELOPER_ID" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
ditto -c -k --keepParent "$APP" dist/StorageViewer-notarise.zip
xcrun notarytool submit dist/StorageViewer-notarise.zip --keychain-profile "$NOTARY_PROFILE" --wait
xcrun stapler staple "$APP"
spctl --assess --type execute --verbose "$APP"
rm -f dist/StorageViewer.dmg
hdiutil create -volname "Storage Viewer" -srcfolder "$APP" -ov -format UDZO dist/StorageViewer.dmg
shasum -a 256 dist/StorageViewer.dmg > dist/StorageViewer.dmg.sha256
echo "Signed, notarised and packaged: dist/StorageViewer.dmg"
