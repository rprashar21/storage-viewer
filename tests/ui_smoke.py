"""Drives the real pywebview window and checks the DOM. macOS only: .venv/bin/python tests/ui_smoke.py"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import webview
from app import Api

fixture = tempfile.TemporaryDirectory()
root = Path(fixture.name).resolve()
(root / 'empty').mkdir()
(root / 'sub').mkdir()
(root / 'sub' / 'pic.png').write_bytes(b'p' * 3000)
for n in ('dup1.bin', 'dup2.bin'):
    (root / n).write_bytes(b'd' * 2_000_000)
(root / 'big.dmg').write_bytes(b'i' * 5000)
(root / 'proj' / 'node_modules').mkdir(parents=True)
(root / 'proj' / 'package.json').write_text('{}')
(root / 'proj' / 'node_modules' / 'm.js').write_bytes(b'm' * 4000)

# Keep dependency scanning inside the test fixture, away from personal folders.
import app as app_module
from refs import scan_presentations as real_scan_presentations
app_module.scan_presentations = lambda folders: real_scan_presentations(
    [folder for folder in folders if Path(folder).is_relative_to(root)])
api = Api()
api._allowed.add(str(root))
trashed = []
api._planner._trash = trashed.append
api._planner._log = root / 'history.jsonl'
from mover import Journal, Mover
from rules import RuleStore
api._journal = Journal(str(root / 'journal.sqlite3'))
api._mover = Mover(api._journal, trash=trashed.append)
api._rules = RuleStore(root / 'rules.json')
from ignore import IgnoreStore
api._ignore = IgnoreStore(root / 'ignored.json')
api._watcher.mover, api._watcher.rules = api._mover, api._rules
org = root / 'org'
(org / 'src').mkdir(parents=True)
(org / 'dest').mkdir()
api._allowed.update({str(org / 'src'), str(org / 'dest')})
import zipfile
(org / 'src' / 'Screenshot 2026-01-02 at 10.00.00.png').write_bytes(b's' * 100)
import struct, zlib
def _chunk(tp, d):
    return struct.pack('>I', len(d)) + tp + d + struct.pack('>I', zlib.crc32(tp + d))
_png = b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 2, 0, 0, 0)) + _chunk(b'IDAT', zlib.compress(b''.join(b'\x00' + b'\xff\x00\x00' * 8 for _ in range(8)))) + _chunk(b'IEND', b'')
(org / 'src' / 'linked.png').write_bytes(_png)
with zipfile.ZipFile(org / 'src' / 'deck.pptx', 'w') as z:
    z.writestr('ppt/slides/_rels/slide1.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="x/image" Target="linked.png" TargetMode="External"/></Relationships>')
html = (Path(__file__).resolve().parent.parent / 'index.html').read_text(encoding='utf-8')
window = webview.create_window('smoke', html=html, js_api=api, width=1080, height=760)
api._window = window
results = []


def js(expr):
    return window.evaluate_js(expr)


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''), flush=True)


def wait(expr, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = js(expr)
            if v:
                return v
        except Exception:
            pass
        time.sleep(0.2)
    return None


LAYOUT_JS = '''(function(){const bad=[];const w=window.innerWidth;if(document.documentElement.scrollWidth>w+1)bad.push('page scrolls sideways: '+document.documentElement.scrollWidth+'>'+w);for(const el of document.querySelectorAll('main *')){if(!el.offsetParent&&getComputedStyle(el).position!=='fixed')continue;const r=el.getBoundingClientRect();if(r.width===0)continue;if(r.left<-1)bad.push('clipped left: '+(el.id||el.tagName)+' '+Math.round(r.left));if(r.right>w+1)bad.push('clipped right: '+(el.id||el.tagName)+' '+Math.round(r.right))}return bad.slice(0,5).join('; ')})()'''


def layout(name):
    problems = js(LAYOUT_JS)
    check(f'layout ok on {name}', not problems, problems)


def run():
    try:
        check('bridge connects, capacity shown', wait("document.getElementById('total').textContent.indexOf('—')<0"))
        check('volumes listed', wait("document.getElementById('volumes').textContent.length>0"))
        check('buttons enabled', js("!document.getElementById('home').disabled"))
        js(f"scan({json.dumps(str(root))})")
        check('scan completes', wait("document.getElementById('status').textContent.startsWith('complete')"))
        check('rows listed', js("document.querySelectorAll('#rows tr').length") >= 4)
        check('largest files shown', js("document.querySelectorAll('#top tr').length") >= 3)
        check('type breakdown shown', 'Images' in js("document.getElementById('types').textContent"))
        check('breadcrumb buttons exist', js("document.querySelectorAll('#path span, #path button').length") > 1)
        js("document.getElementById('sort').value='name';document.getElementById('sort').onchange()")
        first = js("document.querySelector('#rows tr td').textContent")
        check('sort by name', first and first.lower().lstrip('▸ ').startswith('big'), first)
        js("tab('procs')")
        layout('storage tab')
        for width in (760, 1600):
            window.resize(width, 700)
            time.sleep(0.8)
            layout(f'storage tab at {width}px')
        window.resize(1080, 760)
        time.sleep(0.5)
        check('processes render', wait("document.querySelectorAll('#procRows tr').length>5"))
        layout('processes tab')
        check('process summary', 'cores' in js("document.getElementById('procSummary').textContent"))
        js("tab('clean')")
        js(f"review({json.dumps(str(root))})")
        check('cleanup review completes', wait("document.getElementById('cStatus').textContent.startsWith('complete')", 30))
        layout('cleanup tab')
        check('developer clutter found', 'Developer build clutter: 1 item' in js("document.getElementById('cResults').textContent"))
        check('duplicates found', 'Exact duplicates: 2 items' in js("document.getElementById('cResults').textContent"))
        js("[...document.querySelectorAll('#cResults button')].find(b=>b.textContent==='Ignore').click()")
        check('ignore hides an item and lists it', wait("document.getElementById('cIgnored').textContent.includes('/')"))
        js("[...document.querySelectorAll('#cResults button')].find(b=>b.textContent.startsWith('Select all but')).click()")
        check('selection counted', wait("document.getElementById('cBarText').textContent==='1 selected'"))
        js("document.getElementById('cReview').click()")
        check('confirmation shown before moving', wait("!document.getElementById('cConfirm').hidden && document.getElementById('cConfirm').textContent.includes('to the Trash?')"))
        check('nothing trashed before confirm', trashed == [])
        js("document.getElementById('cConfirm').querySelector('button.primary').click()")
        check('move completes', wait("document.getElementById('cConfirm').textContent.startsWith('Moved 1 item')"))
        check('exactly one copy trashed', len(trashed) == 1 and trashed[0].endswith('.bin'), str(trashed))
        # Organise tab
        js("tab('org')")
        js(f"document.getElementById('oSrcDesktop').checked=false;document.getElementById('oSrcDownloads').checked=false;oSources=[{json.dumps(str(org / 'src'))}];oDest={json.dumps(str(org / 'dest'))};document.getElementById('oPreset').value='images'")
        js("oPreview()")
        layout('organise tab')
        check('organise preview rows', wait("document.querySelectorAll('#oRows tr').length===2"), js("document.getElementById('oStatus').textContent"))
        check('thumbnail shown for image row', wait("document.querySelectorAll('#oRows img').length>=1"))
        check('linked image skipped by default', wait("document.getElementById('oBarText').textContent==='1 to move, 0 to copy'"))
        check('presentation wording shown', 'checked presentation' in js("document.getElementById('oNote').textContent"))
        check('preview moved nothing', (org / 'src' / 'linked.png').exists() and (org / 'src' / 'Screenshot 2026-01-02 at 10.00.00.png').exists())
        check('source paths visible', js("document.querySelectorAll('#oRows .source').length===2"))
        js("[...document.querySelectorAll('#oGroups button')].find(b=>b.textContent.startsWith('Needs attention')).click()")
        check('attention filter shows linked file', js("document.querySelectorAll('#oRows tr').length===1 && document.getElementById('oRows').textContent.includes('linked.png')"))
        check('filter preserves selection', js("oSel.size===1"))
        js("document.querySelector('#oGroups button').click()")
        for width in (760, 1600):
            window.resize(width, 760)
            time.sleep(0.3)
            layout(f'organise at {width}px')
        window.resize(1080, 760)
        js("document.getElementById('oApply').click()")
        check('organise confirmation shown', wait("!document.getElementById('oConfirm').hidden && document.getElementById('oConfirm').textContent.includes('Move 1')"))
        check('still nothing moved before confirm', (org / 'src' / 'Screenshot 2026-01-02 at 10.00.00.png').exists())
        js("document.getElementById('oConfirm').querySelector('button.primary').click()")
        check('organise completes', wait("document.getElementById('oConfirm').textContent.startsWith('Done: 1 completed')"))
        check('file moved, linked file kept', (org / 'dest' / 'Screenshot 2026-01-02 at 10.00.00.png').exists() and (org / 'src' / 'linked.png').exists())
        check('history lists batch with undo', wait("[...document.querySelectorAll('#oHistory button')].some(b=>b.textContent==='Undo')"))
        js("[...document.querySelectorAll('#oHistory button')].find(b=>b.textContent==='Undo').click()")
        js("[...document.querySelectorAll('#oHistory button')].find(b=>b.textContent==='Confirm undo').click()")
        check('undo restores file', wait("document.getElementById('oStatus').textContent.startsWith('Undone 1')") and (org / 'src' / 'Screenshot 2026-01-02 at 10.00.00.png').exists())
        js("document.getElementById('rName').value='Shots';document.getElementById('rSave').click()")
        check('rule saved and listed', wait("document.getElementById('rList').textContent.includes('Shots')"))
        js("[...document.querySelectorAll('#rList button')].find(b=>b.textContent==='Watch: auto').click()")
        check('auto watch asks for confirmation', wait("!document.getElementById('wConfirm').hidden"))
        check('watcher not started before confirm', api._watcher.items == {})
        js("document.getElementById('wConfirm').querySelector('button.primary').click()")
        check('watcher starts after confirm', wait("document.getElementById('wList').textContent.includes('Shots')"), js("document.getElementById('oStatus').textContent"))
        js("document.getElementById('wPause').click()")
        check('watcher can be paused', wait("document.getElementById('wList').textContent.includes('paused')"))
        js("document.getElementById('oMode').value='view';oModeChanged();document.getElementById('oPreset').value='by_type';oPreview()")
        check('view mode groups files without move action', wait("oPlan?.mode==='view' && document.getElementById('oApply').disabled && oSel.size===0"))
        check('view mode leaves files in place', (org / 'src' / 'linked.png').exists())
        js("document.getElementById('oMode').value='inside';oModeChanged();oPreview()")
        check('inside preview uses source category folder', wait("oPlan?.mode==='inside' && oPlan.rows.some(r=>r.dst.includes('/src/Images/'))"))
        check('inside preview creates no folders', not (org / 'src' / 'Images').exists())
        js("document.getElementById('oApply').click();document.getElementById('oConfirm').querySelector('button.primary').click()")
        check('inside move creates category folder', wait("document.getElementById('oConfirm').textContent.startsWith('Done:')") and (org / 'src' / 'Images' / 'Screenshot 2026-01-02 at 10.00.00.png').exists())
        check('inside move keeps linked file', (org / 'src' / 'linked.png').exists())
        js("document.getElementById('oTidyDownloads').click()")
        check('tidy Downloads defaults to inside by type', js("document.getElementById('oMode').value==='inside' && document.getElementById('oPreset').value==='by_type' && !document.getElementById('oRec').checked && document.getElementById('oSrcDownloads').checked && !document.getElementById('oSrcDesktop').checked"))
        js("oPlan={id:'fixture',dest:'/dest',blocked:0,linked:0,rows:Array.from({length:125},(_,i)=>({src:'/src/file'+i+'.txt',dst:'/dest/Documents/file'+i+'.txt',status:'ready',warnings:[],referenced_by:[],selected:true,op:'move',reason:'Document',bytes:1}))};oRender()")
        check('large preview renders only 60 rows', js("document.querySelectorAll('#oRows tr').length===60 && oSel.size===125"))
        js("document.querySelector('#oRows input').click();document.getElementById('oNextPage').click()")
        check('page change preserves deselection', js("oSel.size===124 && !oSel.has(0) && document.getElementById('oRows').textContent.includes('file60.txt')"))
        js("document.getElementById('oPrevPage').click()")
        check('returning page restores checkbox state', js("!document.querySelector('#oRows input').checked"))
        api._watcher.shutdown()
        check('other copy remains', sum((root / n).exists() for n in ('dup1.bin', 'dup2.bin')) == 2)  # fake trash did not move it
    finally:
        failed = [r for r in results if not r[1]]
        print(f'\n{len(results) - len(failed)}/{len(results)} UI checks passed', flush=True)
        window.destroy()
        os._exit(1 if failed else 0)


webview.start(lambda: threading.Thread(target=run, daemon=True).start())
