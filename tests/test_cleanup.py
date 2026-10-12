import os
import tempfile
import time
import unittest
from pathlib import Path
from cleanup import CleanupPlanner, protected_reason
from findings import FindingsJob


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'empty').mkdir()
        for name, data in [('d1.bin', b'c' * 100), ('d2.bin', b'c' * 100), ('keep.bin', b'k' * 100)]:
            (self.root / name).write_bytes(data)
        (self.root / 'cert.pem').write_bytes(b'p' * 500)
        job = FindingsJob(self.root, large=400, dup_min=10)
        job.run()
        self.snap = job.snapshot()
        self.trashed = []
        self.planner = CleanupPlanner(trash=self.trashed.append, log_path=self.root / 'log' / 'h.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def p(self, name):
        return str(self.root / name)

    def test_trashes_selected_extra_copy_and_empty_folder(self):
        plan = self.planner.build(self.snap, [self.p('d2.bin'), self.p('empty')])
        self.assertEqual((plan['count'], plan['blocked']), (2, 0))
        result = self.planner.apply(plan['id'])
        self.assertEqual(result['trashed'], 2)
        self.assertEqual(set(self.trashed), {self.p('d2.bin'), self.p('empty')})
        self.assertTrue((self.root / 'log' / 'h.jsonl').exists())

    def test_never_removes_every_copy(self):
        plan = self.planner.build(self.snap, [self.p('d1.bin'), self.p('d2.bin')])
        self.assertEqual(plan['count'], 0)
        self.assertEqual(plan['blocked'], 2)

    def test_blocks_protected_and_unreviewed_paths(self):
        plan = self.planner.build(self.snap, [self.p('cert.pem'), self.p('keep.bin'), '/etc/hosts'])
        self.assertEqual(plan['count'], 0)
        self.assertEqual(plan['blocked'], 3)
        self.assertIsNotNone(protected_reason('/Applications/X.app/Contents/a'))
        self.assertIsNotNone(protected_reason('/Users/a/Library/Caches/x'))

    def test_changed_file_is_skipped(self):
        plan = self.planner.build(self.snap, [self.p('d2.bin')])
        (self.root / 'd2.bin').write_bytes(b'changed!!')
        result = self.planner.apply(plan['id'])
        self.assertEqual(result['trashed'], 0)
        self.assertEqual(self.trashed, [])
        self.assertIn('changed', result['results'][0]['detail'])

    def test_nonempty_folder_and_symlink_skipped(self):
        plan = self.planner.build(self.snap, [self.p('empty'), self.p('d2.bin')])
        (self.root / 'empty' / 'new.txt').write_bytes(b'x')
        os.remove(self.p('d2.bin'))
        os.symlink(self.p('keep.bin'), self.p('d2.bin'))
        result = self.planner.apply(plan['id'])
        self.assertEqual(result['trashed'], 0)

    def test_plan_is_single_use(self):
        plan = self.planner.build(self.snap, [self.p('d2.bin')])
        self.planner.apply(plan['id'])
        with self.assertRaises(ValueError):
            self.planner.apply(plan['id'])


class DevClutterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        proj = self.root / 'app'
        (proj / 'node_modules' / 'pkg').mkdir(parents=True)
        (proj / 'package.json').write_text('{}')
        (proj / 'node_modules' / 'pkg' / 'big.js').write_bytes(b'j' * 5000)
        (self.root / 'loose' / 'node_modules').mkdir(parents=True)          # no package.json: not a finding
        (self.root / 'loose' / 'node_modules' / 'x.js').write_bytes(b'x' * 10)
        derived = self.root / 'Library' / 'Developer' / 'Xcode' / 'DerivedData' / 'App-abc'
        derived.mkdir(parents=True)
        (derived / 'obj.o').write_bytes(b'o' * 3000)
        job = FindingsJob(self.root, large=10**9, dup_min=10**9)
        job.run()
        self.snap = job.snapshot()
        self.trashed = []
        self.planner = CleanupPlanner(trash=self.trashed.append, log_path=self.root / 'h.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_only_real_dev_folders_with_sizes(self):
        dev = {f['rule']: f for f in self.snap['findings']}['dev']
        by = {Path(i['path']).name: i['bytes'] for i in dev['items']}
        self.assertEqual(by, {'node_modules': 5000, 'App-abc': 3000})

    def test_dev_folders_trash_after_plan_including_derived_data(self):
        dev = {f['rule']: f for f in self.snap['findings']}['dev']
        paths = [i['path'] for i in dev['items']]
        plan = self.planner.build(self.snap, paths)
        self.assertEqual((plan['count'], plan['blocked']), (2, 0))
        self.assertEqual(self.planner.apply(plan['id'])['trashed'], 2)
        self.assertEqual(set(self.trashed), set(paths))

    def test_ignored_project_is_never_reported(self):
        from ignore import IgnoreStore
        store = IgnoreStore(self.root / 'ignored.json')
        store.add(str(self.root / 'app'))
        self.assertEqual(store.list(), [str(self.root / 'app')])
        job = FindingsJob(self.root, large=10**9, dup_min=10**9, ignore=store.list())
        job.run()
        dev = {f['rule']: f for f in job.snapshot()['findings']}['dev']
        self.assertEqual([Path(i['path']).name for i in dev['items']], ['App-abc'])
        store.remove(str(self.root / 'app'))
        self.assertEqual(store.list(), [])
        with self.assertRaises(ValueError):
            store.add('/')

    def test_other_library_paths_stay_blocked(self):
        plan = self.planner.build(self.snap, [str(self.root / 'Library' / 'Developer')])
        self.assertEqual(plan['count'], 0)


if __name__ == '__main__':
    unittest.main()
