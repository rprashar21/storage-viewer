"""Write THIRD_PARTY.md from installed package metadata. Run inside the build venv."""
import importlib.metadata as m
import sys

NAMES = ['pywebview', 'pyinstaller', 'psutil', 'send2trash']
rows = []
for dist in sorted(m.distributions(), key=lambda d: d.metadata['Name'].lower()):
    name = dist.metadata['Name']
    lic = dist.metadata.get('License-Expression') or dist.metadata.get('License') or ''
    if not lic or len(lic) > 60:
        lic = next((c.split('::')[-1].strip() for c in dist.metadata.get_all('Classifier') or [] if c.startswith('License ::')), 'see package')
    rows.append(f'| {name} | {dist.version} | {lic} |')
with open(sys.argv[1] if len(sys.argv) > 1 else 'THIRD_PARTY.md', 'w') as f:
    f.write('# Third-party components\n\nGenerated from the build environment. Verify each licence before public release.\n\n'
            '| Package | Version | Licence |\n| --- | --- | --- |\n' + '\n'.join(rows) + '\n')
