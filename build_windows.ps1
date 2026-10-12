# Build StorageViewer.exe on Windows 10/11. Run from PowerShell in this folder:
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name StorageViewer --add-data 'index.html;.' app.py
Write-Host "`nBuilt dist\StorageViewer.exe (single file, nothing to install) (unsigned; SmartScreen will warn)."
