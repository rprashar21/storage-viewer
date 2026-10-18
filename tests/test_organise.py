import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from mover import Journal, Mover
from organise import build_plan, match_rule
from refs import scan_presentations, wording

REL = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       '{}</Relationships>')


def make_pptx(path, targets):
    rels = ''.join(f'<Relationship Id="r{i}" Type="x/image" Target="{t}" TargetMode="External"/>'
                   for i, t in enumerate(targets))
    rels += '<Relationship Id="rE" Type="x/image" Target="../media/image1.png"/>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ppt/slides/_rels/slide1.xml.rels', REL.format(rels))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.src = self.root / 'src'
        self.dst = self.root / 'dest'
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data=b'x', folder=None):
        p = (folder or self.src) / name
        p.write_bytes(data)
        return p


class RuleTests(Base):
    def test_in_place_groups_loose_files_and_reuses_folders(self):
        self.put('clip.mp4')
        self.put('photo.png')
        self.put('unknown.xyz')
        (self.src / 'Images').mkdir()
        self.put('already.png', folder=self.src / 'Images')
        plan = build_plan([str(self.src)], str(self.src), 'by_type', mode='inside')
        targets = {Path(r['dst']).relative_to(self.src).as_posix() for r in plan['rows']}
        self.assertEqual(targets, {'Videos/clip.mp4', 'Images/photo.png', 'Other/unknown.xyz'})
        self.assertFalse((self.src / 'Videos').exists())
        journal = Journal(str(self.root / 'inside.sqlite3'))
        mover = Mover(journal)
        result = mover.apply(plan, {i: 'move' for i in range(len(plan['rows']))})
        self.assertEqual(result['done'], 3)
        self.assertEqual(build_plan([str(self.src)], str(self.src), 'by_type', mode='inside')['rows'], [])
        self.assertTrue((self.src / 'Images' / 'already.png').exists())

    def test_inside_conflicts_symlinks_and_protected_unknowns(self):
        self.put('photo.png')
        (self.src / 'Images').mkdir()
        self.put('photo.png', b'existing', self.src / 'Images')
        self.put('cert.pem')
        (self.src / 'alias.png').symlink_to(self.src / 'photo.png')
        plan = build_plan([str(self.src)], str(self.src), 'by_type', mode='inside')
        photo = next(r for r in plan['rows'] if r['src'].endswith('photo.png'))
        self.assertTrue(photo['warnings'])
        self.assertFalse(any(r['src'].endswith('alias.png') for r in plan['rows']))
        cert = next(r for r in plan['rows'] if r['src'].endswith('cert.pem'))
        self.assertEqual((cert['status'], cert['selected']), ('blocked', False))

    def test_api_never_registers_view_only_plan_for_moves(self):
        from unittest.mock import patch
        from app import Api
        self.put('photo.png')
        api = Api()
        api._allowed.add(str(self.src))
        with patch('app.scan_presentations', return_value={'refs': {}, 'checked': 0, 'unreadable': [], 'folders': []}):
            plan = api.organise_preview([str(self.src)], '', 'by_type', mode='view')
        with self.assertRaises(ValueError):
            api.organise_apply(plan['id'], {'0': 'move'})
        self.assertTrue((self.src / 'photo.png').exists())
        api._watcher.shutdown()

    def test_view_plan_selects_nothing_and_has_distinct_id(self):
        self.put('photo.png')
        view = build_plan([str(self.src)], str(self.src), 'by_type', mode='view')
        move = build_plan([str(self.src)], str(self.src), 'by_type', mode='inside')
        self.assertFalse(any(r['selected'] for r in view['rows']))
        self.assertNotEqual(view['id'], move['id'])
        self.assertEqual(list(self.src.iterdir()), [self.src / 'photo.png'])

    def test_in_place_single_type_gets_category_folder(self):
        self.put('clip.mp4')
        plan = build_plan([str(self.src)], str(self.src), 'videos', mode='inside')
        self.assertEqual(Path(plan['rows'][0]['dst']), self.src / 'Videos' / 'clip.mp4')

    def test_inside_rejects_recursion_and_multiple_sources(self):
        for sources, recursive in [([str(self.src)], True), ([str(self.src), str(self.dst)], False)]:
            with self.assertRaises(ValueError):
                build_plan(sources, str(self.src), 'by_type', recursive=recursive, mode='inside')

    def test_png_alone_is_not_a_screenshot(self):
        self.assertIsNone(match_rule('photo.png', 'screenshots'))
        self.assertIsNotNone(match_rule('Screenshot 2026-10-11 at 17.46.11.png', 'screenshots'))
        self.assertIsNone(match_rule('Screenshot notes.txt', 'screenshots'))

    def test_plan_is_deterministic_and_previews_only(self):
        self.put('Screenshot 2026-01-02 at 10.00.00.png', b'a')
        self.put('notes.pdf', b'b')
        p1 = build_plan([str(self.src)], str(self.dst), 'screenshots')
        p2 = build_plan([str(self.src)], str(self.dst), 'screenshots')
        self.assertEqual(p1['id'], p2['id'])
        self.assertEqual(len(p1['rows']), 1)
        self.assertEqual(os.listdir(self.src).__len__(), 2)
        self.assertEqual(os.listdir(self.dst), [])

    def test_group_by_month_and_by_type(self):
        f = self.put('a.pdf')
        os.utime(f, (1_700_000_000, 1_700_000_000))
        plan = build_plan([str(self.src)], str(self.dst), 'by_type', 'month')
        self.assertTrue(plan['rows'][0]['dst'].endswith(os.path.join('Documents', '2023-11', 'a.pdf')))

    def test_subfolders_untouched_unless_recursive(self):
        (self.src / 'sub').mkdir()
        self.put('deep.pdf', folder=self.src / 'sub')
        self.assertEqual(build_plan([str(self.src)], str(self.dst), 'documents')['rows'], [])
        self.assertEqual(len(build_plan([str(self.src)], str(self.dst), 'documents', recursive=True)['rows']), 1)

    def test_destination_excluded_and_app_bundles_skipped(self):
        self.put('already.pdf', folder=self.dst)
        (self.src / 'X.app').mkdir()
        self.put('inner.pdf', folder=self.src / 'X.app')
        plan = build_plan([str(self.src), str(self.root)], str(self.dst), 'documents', recursive=True)
        self.assertEqual(plan['rows'], [])

    def test_destination_cannot_be_source(self):
        with self.assertRaises(ValueError):
            build_plan([str(self.src)], str(self.src), 'documents')

    def test_protected_files_blocked(self):
        self.put('cert.pem')
        plan = build_plan([str(self.src)], str(self.dst), 'by_type')
        self.assertEqual(plan['rows'], [])  # .pem is not a known category: never proposed


class PresentationTests(Base):
    def test_linked_image_detected_and_embedded_ignored(self):
        img = self.put('chart.png', b'img')
        make_pptx(self.root / 'deck.pptx', [f'file://{img}', 'https://example.com/a.png'])
        res = scan_presentations([str(self.root)])
        self.assertEqual(res['checked'], 1)
        self.assertEqual(len(res['refs']), 1)
        plan = build_plan([str(self.src)], str(self.dst), 'images', ref_index=res)
        row = plan['rows'][0]
        self.assertEqual((row['op'], row['selected'], row['status']), ('skip', False, 'ready'))
        self.assertTrue(row['referenced_by'][0].endswith('deck.pptx'))
        self.assertEqual(plan['linked'], 1)

    def test_relative_link_resolves_and_unreadable_reported(self):
        self.put('rel.png', b'img')
        make_pptx(self.src / 'deck.pptx', ['rel.png'])
        (self.root / 'bad.pptx').write_bytes(b'not a zip')
        res = scan_presentations([str(self.root)])
        self.assertEqual(res['checked'], 1)
        self.assertEqual(len(res['unreadable']), 1)
        self.assertIn('could not be checked', wording(res))
        self.assertTrue(any(k.endswith('rel.png') for k in res['refs']))

    def test_clean_wording(self):
        make_pptx(self.root / 'a.pptx', [])
        self.assertEqual(wording(scan_presentations([str(self.root)])),
                         'No references found in the 1 checked presentation.')


class MoverTests(Base):
    def setUp(self):
        super().setUp()
        self.j = Journal(':memory:')
        self.trash = []
        self.m = Mover(self.j, trash=self.trash.append)
        self.addCleanup(self.j.close)

    def plan(self, **kw):
        return build_plan([str(self.src)], str(self.dst), 'documents', **kw)

    def test_move_journal_and_undo(self):
        a = self.put('a.pdf', b'aaa')
        plan = self.plan()
        res = self.m.apply(plan, {0: 'move'})
        self.assertEqual(res['done'], 1)
        self.assertFalse(a.exists())
        self.assertTrue((self.dst / 'a.pdf').exists())
        self.assertEqual(self.j.batches()[0]['counts'], {'done': 1})
        undo = self.m.undo(res['batch'])
        self.assertEqual(undo['undone'], 1)
        self.assertTrue(a.exists())
        self.assertFalse((self.dst / 'a.pdf').exists())

    def test_never_overwrites_renames_or_skips(self):
        self.put('a.pdf', b'new')
        self.put('a.pdf', b'old', folder=self.dst)
        res = self.m.apply(self.plan(), {0: 'move'})
        self.assertEqual((self.dst / 'a.pdf').read_bytes(), b'old')
        self.assertEqual((self.dst / 'a (1).pdf').read_bytes(), b'new')
        self.assertEqual(res['done'], 1)
        self.put('b.pdf', b'n2')
        self.put('b.pdf', b'o2', folder=self.dst)
        plan = self.plan(conflict='skip')
        idx = [r['src'].endswith('b.pdf') for r in plan['rows']].index(True)
        res = self.m.apply(plan, {idx: 'move'})
        self.assertEqual(res['skipped'], 1)
        self.assertTrue((self.src / 'b.pdf').exists())

    def test_changed_file_skipped_and_unchosen_untouched(self):
        a = self.put('a.pdf', b'aaa')
        b = self.put('b.pdf', b'bbb')
        plan = self.plan()
        a.write_bytes(b'changed content')
        res = self.m.apply(plan, {0: 'move'})
        self.assertEqual(res['skipped'], 1)
        self.assertTrue(a.exists() and b.exists())

    def test_copy_keeps_original_and_undo_trashes_copy(self):
        a = self.put('a.pdf', b'aaa')
        res = self.m.apply(self.plan(), {0: 'copy'})
        self.assertTrue(a.exists() and (self.dst / 'a.pdf').exists())
        self.m.undo(res['batch'])
        self.assertEqual(self.trash, [str(self.dst / 'a.pdf')])

    def test_undo_refuses_when_original_path_occupied_or_file_changed(self):
        a = self.put('a.pdf', b'aaa')
        res = self.m.apply(self.plan(), {0: 'move'})
        self.put('a.pdf', b'someone else')
        undo = self.m.undo(res['batch'])
        self.assertEqual(undo['undone'], 0)
        self.assertEqual(a.read_bytes(), b'someone else')
        self.assertTrue((self.dst / 'a.pdf').exists())

    def test_reconcile_after_crash_between_link_and_unlink(self):
        a = self.put('a.pdf', b'aaa')
        bid = self.j.add_batch('x', 'p')
        self.j.add_op(bid, 0, 'move', str(a), str(self.dst / 'a.pdf'), 3, a.stat().st_mtime)
        os.link(a, self.dst / 'a.pdf')
        self.assertEqual(self.m.reconcile(), 1)
        self.assertFalse(a.exists())
        self.assertEqual(self.j.ops(bid)[0]['status'], 'done')

    def test_reconcile_interrupted_before_change(self):
        a = self.put('a.pdf', b'aaa')
        bid = self.j.add_batch('x', 'p')
        self.j.add_op(bid, 0, 'move', str(a), str(self.dst / 'a.pdf'), 3, 0)
        self.m.reconcile()
        self.assertEqual(self.j.ops(bid)[0]['status'], 'failed')
        self.assertTrue(a.exists())


if __name__ == '__main__':
    unittest.main()


class RuleStoreTests(Base):
    def rule(self, **kw):
        r = {'name': 'Shots', 'sources': [str(self.src)], 'dest': str(self.dst), 'preset': 'screenshots'}
        r.update(kw)
        return r

    def test_save_export_import_roundtrip(self):
        from rules import RuleStore
        store = RuleStore(self.root / 'rules.json')
        store.save(self.rule())
        text = store.export_text()
        other = RuleStore(self.root / 'other.json')
        self.assertEqual(other.import_text(text)[0]['name'], 'Shots')
        self.assertEqual(len(other.list()), 1)

    def test_rejects_executable_or_malformed_rules(self):
        from rules import validate
        for bad in [self.rule(command='rm -rf /'), self.rule(preset='run'), self.rule(sources=['relative']),
                    self.rule(dest=str(self.src)), self.rule(priority=999), self.rule(name=' ')]:
            with self.assertRaises(ValueError):
                validate(bad)

    def test_import_rejects_foreign_files(self):
        from rules import RuleStore
        with self.assertRaises(ValueError):
            RuleStore(self.root / 'r.json').import_text('{"actions": [{"shell": "x"}]}')

    def test_conflicts_reported(self):
        from rules import conflicts, validate
        a = validate(self.rule())
        b = validate(self.rule(name='Other', dest=str(self.root / 'elsewhere'), preset='by_type'))
        self.assertEqual(len(conflicts([a, b])), 1)


class CrossVolumeTests(Base):
    def setUp(self):
        super().setUp()
        self.j = Journal(':memory:')
        self.addCleanup(self.j.close)
        self.m = Mover(self.j, trash=lambda p: None)

    def plan(self):
        return build_plan([str(self.src)], str(self.dst), 'documents')

    def test_cross_volume_copy_verify_then_remove_and_undo(self):
        from unittest.mock import patch
        a = self.put('a.pdf', b'payload' * 1000)
        with patch('mover.different_volume', return_value=True):
            res = self.m.apply(self.plan(), {0: 'move'})
            self.assertEqual(res['done'], 1)
            self.assertFalse(a.exists())
            self.assertEqual((self.dst / 'a.pdf').read_bytes(), b'payload' * 1000)
            self.assertEqual([p.name for p in self.dst.iterdir()], ['a.pdf'])
            self.assertEqual(self.m.undo(res['batch'])['undone'], 1)
        self.assertTrue(a.exists())

    def test_disk_full_leaves_original_and_no_partial_file(self):
        from unittest.mock import patch
        a = self.put('a.pdf', b'x' * 100)
        real_open = open

        def failing_open(path, mode='r', *args, **kw):
            fh = real_open(path, mode, *args, **kw)
            if 'xb' in mode:
                fh.write = lambda data: (_ for _ in ()).throw(OSError(28, 'No space left on device'))
            return fh
        with patch('mover.different_volume', return_value=True), patch('builtins.open', failing_open):
            res = self.m.apply(self.plan(), {0: 'move'})
        self.assertEqual(res['failed'], 1)
        self.assertTrue(a.exists())
        self.assertEqual(list(self.dst.iterdir()), [])

    def test_failed_verification_keeps_original(self):
        from unittest.mock import patch
        a = self.put('a.pdf', b'x' * 100)
        with patch('mover.different_volume', return_value=True), patch('mover._sha', return_value='bad'):
            res = self.m.apply(self.plan(), {0: 'move'})
        self.assertEqual(res['failed'], 1)
        self.assertTrue(a.exists())
        self.assertEqual(list(self.dst.iterdir()), [])

    def test_interruption_cleans_temp_and_reconcile_settles_duplicates(self):
        from unittest.mock import patch
        a = self.put('a.pdf', b'x' * 100)
        with patch('mover.different_volume', return_value=True), \
                patch('mover.os.fsync', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.m.apply(self.plan(), {0: 'move'})
        self.assertTrue(a.exists())
        self.assertEqual(list(self.dst.iterdir()), [])
        # crash after copy but before the original was removed: both files, identical bytes
        (self.dst / 'a.pdf').write_bytes(b'x' * 100)
        self.assertEqual(self.m.reconcile(), 1)
        self.assertFalse(a.exists())


class ThumbnailTests(Base):
    def test_rejects_non_images_large_files_and_links(self):
        from thumbs import thumbnail
        self.put('a.txt')
        self.assertIsNone(thumbnail(str(self.src / 'a.txt')))
        self.put('real.png', b'x')
        os.symlink(self.src / 'real.png', self.src / 'link.png')
        self.assertIsNone(thumbnail(str(self.src / 'link.png')))

    def test_real_sips_thumbnail_on_macos(self):
        import shutil
        import struct
        import zlib
        if not shutil.which('sips'):
            self.skipTest('sips not available')
        from thumbs import thumbnail

        def chunk(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
        raw = b''.join(b'\x00' + b'\xff\x00\x00' * 8 for _ in range(8))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 2, 0, 0, 0)) + \
            chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
        self.put('p.png', png)
        self.assertTrue(thumbnail(str(self.src / 'p.png')).startswith('data:image/png;base64,'))


class WatcherTests(Base):
    def setUp(self):
        super().setUp()
        from rules import RuleStore
        from watcher import Watcher
        self.j = Journal(':memory:')
        self.addCleanup(self.j.close)
        self.mover = Mover(self.j, trash=lambda p: None)
        self.store = RuleStore(self.root / 'rules.json')
        self.store.save({'name': 'Docs', 'sources': [str(self.src)], 'dest': str(self.dst), 'preset': 'documents',
                         'exclude': ['skipme']})
        self.now = [time.time()]
        self.w = Watcher(self.mover, self.store, lambda r: (r['sources'], r['dest']), clock=lambda: self.now[0])

    def old(self, name, data=b'x'):
        p = self.put(name, data)
        t = time.time() - 600
        os.utime(p, (t, t))
        return p

    def test_starts_paused_and_suggest_never_moves(self):
        self.old('a.pdf')
        self.assertTrue(self.w.paused)
        self.w.tick()
        self.assertEqual(self.w.items, {})
        self.w.start('Docs', 'suggest')
        self.w.tick()
        self.w.tick()
        self.assertEqual(self.w.status()['items'][0]['pending'], 1)
        self.assertTrue((self.src / 'a.pdf').exists())

    def test_auto_waits_for_stable_files_and_ignores_partials_and_exclusions(self):
        self.old('a.pdf')
        self.old('b.pdf.crdownload')
        self.old('skipme.pdf')
        self.w.start('Docs', 'auto')
        self.w.tick()                      # first sighting: not yet stable
        self.assertTrue((self.src / 'a.pdf').exists())
        self.w.tick()                      # unchanged since last poll: moved
        self.assertTrue((self.dst / 'a.pdf').exists())
        self.assertTrue((self.src / 'b.pdf.crdownload').exists())
        self.assertTrue((self.src / 'skipme.pdf').exists())
        self.assertEqual(self.j.batches()[0]['counts'], {'done': 1})
        self.assertTrue(self.mover.undo(self.j.batches()[0]['id'])['undone'])

    def test_growing_file_not_moved(self):
        f = self.old('grow.pdf', b'1')
        self.w.start('Docs', 'auto')
        self.w.tick()
        f.write_bytes(b'12')
        t = time.time() - 600
        os.utime(f, (t, t))
        self.w.tick()
        self.assertTrue(f.exists())

    def test_pause_stops_work(self):
        self.old('a.pdf')
        self.w.start('Docs', 'auto')
        self.w.set_paused(True)
        self.w.tick()
        self.w.tick()
        self.assertTrue((self.src / 'a.pdf').exists())


class WatcherLinkedTests(WatcherTests):
    def test_linked_file_never_moved_automatically(self):
        img = self.old('chart.png', b'img')
        make_pptx(self.src / 'deck.pptx', [f'file://{img}'])
        self.store.save({'name': 'Imgs', 'sources': [str(self.src)], 'dest': str(self.dst), 'preset': 'images'})
        self.w.start('Imgs', 'auto')
        self.w.tick()
        self.w.tick()
        self.assertTrue(img.exists())


class AdapterTests(unittest.TestCase):
    def test_adapter_interface(self):
        from platform_adapter import MacAdapter, PosixAdapter, get_adapter
        a = get_adapter()
        self.assertTrue(a.volumes())
        self.assertEqual(set(a.standard_folders()), {'Desktop', 'Downloads', 'Documents', 'Pictures'})
        self.assertIsNotNone(PosixAdapter().protected_reason('/x/cert.pem'))
        self.assertIsNone(PosixAdapter().protected_reason('/x/Library/a.txt'))
        self.assertIsNotNone(MacAdapter().protected_reason('/x/Library/a.txt'))
        self.assertTrue(str(MacAdapter().app_support_dir()).endswith('Library/Application Support/StorageViewer'))
