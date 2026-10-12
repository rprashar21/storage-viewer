"""Saved organisation rules: declarative JSON only. Never executes anything from an import."""
import json
import os
from pathlib import Path

from organise import GROUPS, PRESETS

from platform_adapter import get_adapter

DEFAULT_PATH = get_adapter().app_support_dir() / 'rules.json'
VERSION = 1
KEYS = {'name', 'sources', 'dest', 'preset', 'group_by', 'recursive', 'conflict', 'priority', 'exclude', 'version'}


def validate(rule):
    if not isinstance(rule, dict):
        raise ValueError('A rule must be an object')
    extra = set(rule) - KEYS
    if extra:
        raise ValueError('Unknown fields: ' + ', '.join(sorted(extra)))
    name = rule.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError('Rule name must be 1 to 60 characters')
    sources = rule.get('sources')
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and os.path.isabs(s) for s in sources):
        raise ValueError('Sources must be a list of absolute folder paths')
    dest = rule.get('dest')
    if not isinstance(dest, str) or not os.path.isabs(dest):
        raise ValueError('Destination must be an absolute folder path')
    if dest in sources:
        raise ValueError('Destination cannot be a source')
    if rule.get('preset') not in PRESETS:
        raise ValueError('Unknown preset')
    group_by = rule.get('group_by', 'none')
    conflict = rule.get('conflict', 'rename')
    priority = rule.get('priority', 50)
    exclude = rule.get('exclude', [])
    if group_by not in GROUPS or conflict not in ('rename', 'skip'):
        raise ValueError('Unknown option')
    if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 100:
        raise ValueError('Priority must be a whole number from 0 to 100')
    if not isinstance(exclude, list) or not all(isinstance(e, str) and len(e) <= 80 for e in exclude):
        raise ValueError('Exclusions must be a list of file name fragments')
    if rule.get('version', VERSION) != VERSION:
        raise ValueError('Unsupported rule version')
    return {'name': name.strip(), 'sources': list(sources), 'dest': dest, 'preset': rule['preset'],
            'group_by': group_by, 'recursive': bool(rule.get('recursive', False)), 'conflict': conflict,
            'priority': priority, 'exclude': list(exclude), 'version': VERSION}


def conflicts(rules):
    """Rules with an overlapping source and preset but different destinations."""
    out = []
    for i, a in enumerate(rules):
        for b in rules[i + 1:]:
            same_src = set(a['sources']) & set(b['sources'])
            overlap = a['preset'] == b['preset'] or 'by_type' in (a['preset'], b['preset'])
            if same_src and overlap and a['dest'] != b['dest']:
                out.append({'a': a['name'], 'b': b['name'],
                            'detail': 'Overlapping sources and presets with different destinations. '
                                      'The higher priority number is previewed first.'})
    return out


class RuleStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)

    def list(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return [validate(r) for r in data]
        except (OSError, ValueError):
            return []

    def _write(self, rules):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(rules, key=lambda r: (-r['priority'], r['name'].casefold())), indent=2),
                             encoding='utf-8')

    def save(self, rule):
        rule = validate(rule)
        rules = [r for r in self.list() if r['name'] != rule['name']] + [rule]
        self._write(rules)
        return rule

    def delete(self, name):
        self._write([r for r in self.list() if r['name'] != name])

    def export_text(self, names=None):
        rules = [r for r in self.list() if names is None or r['name'] in names]
        return json.dumps({'storage_viewer_rules': VERSION, 'rules': rules}, indent=2)

    def import_text(self, text):
        try:
            data = json.loads(text)
        except ValueError:
            raise ValueError('Not valid JSON')
        if not isinstance(data, dict) or data.get('storage_viewer_rules') != VERSION or not isinstance(data.get('rules'), list):
            raise ValueError('Not a Storage Viewer rules file')
        incoming = [validate(r) for r in data['rules']]
        names = {r['name'] for r in incoming}
        self._write([r for r in self.list() if r['name'] not in names] + incoming)
        return incoming
