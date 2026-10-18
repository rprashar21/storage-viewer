"""Local desktop shell. No HTTP server, remote resources, or file mutations."""
import os
import shutil
import threading
from pathlib import Path
from scanner import ScanJob
from processes import ProcessSampler
from findings import FindingsJob
from ignore import IgnoreStore
from cleanup import CleanupPlanner
from platform_adapter import get_adapter
from mover import Journal, Mover
from organise import build_plan
from refs import scan_presentations, wording
from rules import RuleStore, conflicts
from thumbs import MAX_COUNT, thumbnail
from watcher import Watcher


class Api:
    def __init__(self):
        self._window = None
        self._job = None
        self._lock = threading.Lock()
        self._sampler = ProcessSampler()
        self._findings = None
        self._planner = CleanupPlanner()
        self._journal = Journal()
        self._mover = Mover(self._journal)
        self._mover.reconcile()
        self._rules = RuleStore()
        self._org_plans = {}
        self._ignore = IgnoreStore()
        self._watcher = Watcher(self._mover, self._rules, self._resolve_rule)
        home = Path.home().resolve()
        self._allowed = {str(home)} | set(get_adapter().roots()) | set(get_adapter().standard_folders().values())

    def overview(self):
        usage = shutil.disk_usage(Path.home())
        return {'home': str(Path.home().resolve()), 'total': usage.total,
                'used': usage.used, 'free': usage.free, 'sep': os.sep,
                'root': get_adapter().roots()[0] if os.sep == '/' else Path.home().resolve().anchor,
                'trash': get_adapter().trash_name, 'restore': get_adapter().trash_restore}

    def volumes(self):
        return get_adapter().volumes()

    def processes(self):
        return self._sampler.sample()

    def start_findings(self, path):
        path = str(Path(path).expanduser().resolve())
        with self._lock:
            if self._findings and self._findings.snapshot()['status'] == 'scanning':
                raise ValueError('Wait for the current review to finish.')
            if path not in self._allowed:
                raise ValueError('Choose this folder with the folder picker first.')
            if not Path(path).is_dir():
                raise ValueError('Folder no longer exists.')
            self._findings = FindingsJob(path, ignore=self._ignore.list())
            threading.Thread(target=self._findings.run, daemon=True).start()
        return True

    def ignore_add(self, path):
        self._ignore.add(path)
        return self._ignore.list()

    def ignore_remove(self, path):
        self._ignore.remove(path)
        return self._ignore.list()

    def ignore_list(self):
        return self._ignore.list()

    def findings_status(self):
        with self._lock:
            return self._findings.snapshot() if self._findings else None

    def preview_cleanup(self, paths):
        with self._lock:
            snap = self._findings.snapshot() if self._findings else None
        if not snap or snap['status'] not in ('complete', 'partial'):
            raise ValueError('Finish a cleanup review first.')
        return self._planner.build(snap, list(paths))

    def apply_cleanup(self, plan_id):
        return self._planner.apply(plan_id)

    def _ok_folder(self, path):
        p = str(Path(path).expanduser().resolve())
        with self._lock:
            ok = p in self._allowed or str(Path(p).parent) in self._allowed
        if not ok:
            raise ValueError('Choose this folder with the folder picker first.')
        return p

    def organise_preview(self, sources, dest, preset, group_by='none', recursive=False, conflict='rename', mode='elsewhere'):
        srcs = [self._ok_folder(s) for s in sources]
        dest = self._ok_folder(dest) if mode == 'elsewhere' else (srcs[0] if srcs else '')
        for s in srcs:
            if not Path(s).is_dir():
                raise ValueError('Folder no longer exists: ' + s)
        std = get_adapter().standard_folders()
        folders = list(dict.fromkeys(srcs + [std[d] for d in ('Documents', 'Desktop', 'Downloads')]))
        index = scan_presentations([f for f in folders if Path(f).is_dir()])
        plan = build_plan(srcs, dest, preset, group_by, bool(recursive), conflict, index, mode=mode)
        plan['presentation_note'] = wording(index)
        if mode != 'view':
            self._org_plans[plan['id']] = plan
        with self._lock:
            self._allowed.add(dest)
        return plan

    def organise_apply(self, plan_id, choices):
        plan = self._org_plans.pop(plan_id, None)
        if plan is None:
            raise ValueError('This confirmation expired. Preview again.')
        picked = {}
        for i, op in dict(choices).items():
            i = int(i)
            if op not in ('move', 'copy') or not 0 <= i < len(plan['rows']):
                continue
            if plan['rows'][i]['referenced_by'] and op == 'move':
                continue  # linked from a presentation: copy only, never move
            picked[i] = op
        return self._mover.apply(plan, picked)

    def thumbnails(self, plan_id, indexes):
        plan = self._org_plans.get(plan_id)
        out = {}
        for i in list(indexes)[:MAX_COUNT]:
            if plan and 0 <= int(i) < len(plan['rows']) and plan['rows'][int(i)]['status'] == 'ready':
                uri = thumbnail(plan['rows'][int(i)]['src'])
                if uri:
                    out[int(i)] = uri
        return out

    def _resolve_rule(self, rule):
        srcs = [self._ok_folder(s) for s in rule['sources']]
        return srcs, self._ok_folder(rule['dest'])

    def watch_start(self, name, mode):
        self._watcher.start(name, mode)
        return self._watcher.status()

    def watch_stop(self, name):
        self._watcher.stop(name)
        return self._watcher.status()

    def watch_pause(self, paused):
        self._watcher.set_paused(paused)
        return self._watcher.status()

    def watch_status(self):
        return self._watcher.status()

    def history(self):
        return self._journal.batches()

    def undo(self, batch):
        return self._mover.undo(batch)

    def rules_list(self):
        rules = self._rules.list()
        return {'rules': rules, 'conflicts': conflicts(rules)}

    def rules_save(self, rule):
        return self._rules.save(rule)

    def rules_delete(self, name):
        self._rules.delete(name)
        return True

    def rules_export(self):
        return self._rules.export_text()

    def rules_import(self, text):
        return self._rules.import_text(text)

    def choose_folder(self):
        import webview
        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if selected:
            path = str(Path(selected[0]).resolve())
            with self._lock:
                self._allowed.add(path)
            return path
        return None

    def start_scan(self, path):
        path = str(Path(path).expanduser().resolve())
        with self._lock:
            if self._job and self._job.snapshot()['status'] == 'scanning':
                raise ValueError('Cancel the current scan and wait for it to stop.')
            if path not in self._allowed:
                raise ValueError('Choose this folder with the folder picker first.')
            if not Path(path).is_dir():
                raise ValueError('Folder no longer exists.')
            self._job = ScanJob(path)
            threading.Thread(target=self._job.run, daemon=True).start()
        return True

    def scan_status(self):
        with self._lock:
            if not self._job:
                return None
            result = self._job.snapshot()
            for row in result['rows']:
                if row['kind'] == 'folder':
                    self._allowed.add(str(Path(row['path']).resolve()))
            return result

    def cancel_scan(self):
        with self._lock:
            if self._findings:
                self._findings.cancelled.set()
            if self._job:
                self._job.cancelled.set()
        return True


def main():
    import webview
    api = Api()
    html = Path(__file__).with_name('index.html').read_text(encoding='utf-8')
    api._window = webview.create_window('Storage Viewer', html=html, js_api=api,
                                       width=1080, height=760, min_size=(760, 540))
    api._window.events.closed += api.cancel_scan
    api._window.events.closed += api._watcher.shutdown
    webview.start(debug=False)


if __name__ == '__main__':
    main()
