#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(uname -s)" != Darwin ]; then
  echo 'Build this macOS app on a Mac.' >&2
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name 'StorageViewer' --osx-bundle-identifier 'com.storageviewer.desktop' \
  --add-data 'index.html:.' app.py
(cd dist && ditto -c -k --keepParent StorageViewer.app StorageViewer.zip && shasum -a 256 StorageViewer.zip > StorageViewer.zip.sha256)
printf '\nBuilt dist/StorageViewer.app. This local build is not Developer-ID signed or notarised.\n'
