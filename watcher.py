"""Opt-in background watcher. Polls saved rules while the app is open; starts paused after launch.

'suggest' only counts matching files. 'auto' moves files that look finished (unchanged
between two polls, old enough, not a partial download) through the normal journalled Mover,
so every automatic batch appears in History and can be undone. Linked presentation files
are never moved automatically.
"""
import os
import threading
import time

from organise import build_plan
from refs import scan_presentations

PARTIAL = ('.crdownload', '.part', '.download', '.tmp', '.partial', '.opdownload')
MAX_PER_TICK = 25
MIN_AGE = 10
REFS_TTL = 600


class Watcher:
    def __init__(self, mover, rule_store, resolve, interval=30, clock=time.time):
        self.mover, self.rules, self.resolve = mover, rule_store, resolve
        self.interval, self.clock = interval, clock
        self.items = {}      # name -> {'mode','pending','last'}
        self.paused = True
        self.log = []
        self._seen = {}      # path -> (size, mtime)
        self._refs, self._refs_at = None, 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _note(self, text):
        self.log.append({'at': self.clock(), 'text': text})
        del self.log[:-50]

    def start(self, name, mode):
        if mode not in ('suggest', 'auto'):
            raise ValueError('Mode must be suggest or auto')
        rule = next((r for r in self.rules.list() if r['name'] == name), None)
        if not rule:
            raise ValueError('Unknown rule')
        self.resolve(rule)  # raises if a folder is not approved
        with self._lock:
            self.items[name] = {'mode': mode, 'pending': 0, 'last': None}
            self.paused = False
            self._note(f'Watching "{name}" in {mode} mode')
        self._ensure_thread()

    def stop(self, name):
        with self._lock:
            self.items.pop(name, None)
            self._note(f'Stopped watching "{name}"')

    def set_paused(self, paused):
        with self._lock:
            self.paused = bool(paused)
            self._note('Paused' if paused else 'Resumed')

    def status(self):
        with self._lock:
            return {'paused': self.paused, 'items': [dict(v, name=k) for k, v in self.items.items()],
                    'log': list(self.log)}

    def _ensure_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def shutdown(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.interval):
            self.tick()

    def _ref_index(self, folders):
        if self._refs is None or self.clock() - self._refs_at > REFS_TTL:
            self._refs = scan_presentations(folders)
            self._refs_at = self.clock()
        return self._refs

    def tick(self):
        with self._lock:
            if self.paused:
                return
            active = dict(self.items)
        for name, item in active.items():
            rule = next((r for r in self.rules.list() if r['name'] == name), None)
            if not rule:
                continue
            try:
                srcs, dest = self.resolve(rule)
                index = self._ref_index(srcs)
                plan = build_plan(srcs, dest, rule['preset'], rule['group_by'], rule['recursive'],
                                  rule['conflict'], index)
                choices, now = {}, self.clock()
                skip_words = [w.casefold() for w in rule['exclude']]
                current = {}
                for i, row in enumerate(plan['rows']):
                    if row['status'] != 'ready' or row['referenced_by']:
                        continue
                    base = row['src'].casefold()
                    if base.endswith(PARTIAL) or any(w in os.path.basename(base) for w in skip_words):
                        continue
                    sig = (row['bytes'], int(row['mtime']))
                    current[row['src']] = sig
                    stable = self._seen.get(row['src']) == sig and now - row['mtime'] >= MIN_AGE
                    if stable and len(choices) < MAX_PER_TICK:
                        choices[i] = 'move'
                self._seen.update(current)
                with self._lock:
                    item['pending'] = len(current)
                    item['last'] = now
                if item['mode'] == 'auto' and choices:
                    result = self.mover.apply(plan, choices)
                    with self._lock:
                        self._note(f'"{name}": moved {result["done"]}, skipped {result["skipped"]}, '
                                   f'failed {result["failed"]} (batch {result["batch"]})')
            except Exception as exc:
                with self._lock:
                    self._note(f'"{name}": {exc}')
