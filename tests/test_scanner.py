import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scanner import ScanJob
from app import Api

class ScannerTests(unittest.TestCase):
    def test_nested_sizes_links_and_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'folder').mkdir()
            (root/'empty').mkdir()
            (root/'folder'/'<image>.png').write_bytes(b'x'*11)
            (root/'file.txt').write_bytes(b'x'*3)
            (root/'folder'/'loop').symlink_to(root, target_is_directory=True)
            job = ScanJob(root)
            job.run()
            s = job.snapshot()
            self.assertEqual((s['bytes'],s['files'],s['links']), (14,2,1))
            self.assertEqual(s['status'],'complete')
            self.assertEqual(s['rows'][0]['name'],'folder')
            self.assertEqual(s['rows'][-1]['bytes'],0)
    def test_top_files_largest_first_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'d').mkdir()
            for i in range(25):
                (root/'d'/f'f{i}').write_bytes(b'x'*(i+1))
            job=ScanJob(root)
            job.run()
            top=job.snapshot()['top_files']
            self.assertEqual(len(top),20)
            self.assertEqual([f['bytes'] for f in top],list(range(25,5,-1)))
    def test_elapsed_freezes_after_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'a').write_bytes(b'x')
            job=ScanJob(root)
            job.run()
            first=job.snapshot()['elapsed']
            time.sleep(0.2)
            self.assertEqual(job.snapshot()['elapsed'],first)
    def test_other_volume_directories_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'mnt').mkdir()
            (root/'mnt'/'f').write_bytes(b'x'*5)
            (root/'own').mkdir()
            (root/'own'/'f').write_bytes(b'x'*2)
            job=ScanJob(root)
            real=os.scandir
            class Entry:
                def __init__(s,e): s.e=e; s.name=e.name; s.path=e.path
                def stat(s,follow_symlinks=True):
                    i=s.e.stat(follow_symlinks=follow_symlinks)
                    if s.name=='mnt':
                        return os.stat_result((i.st_mode,i.st_ino,i.st_dev+1,i.st_nlink,i.st_uid,i.st_gid,i.st_size,0,0,0))
                    return i
            class Scan:
                def __init__(s,p): s.c=real(p)
                def __enter__(s): return (Entry(e) for e in s.c.__enter__())
                def __exit__(s,*a): return s.c.__exit__(*a)
            with patch('scanner.os.scandir',side_effect=Scan):
                job.run()
            st=job.snapshot()
            self.assertEqual(st['bytes'],2)
            self.assertEqual(st['mounts_skipped'],1)
    def test_volumes_lists_root(self):
        self.assertTrue(any(v['mount']=='/' for v in Api().volumes()))
    def test_type_breakdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'a.png').write_bytes(b'x'*4)
            (root/'b.MP4').write_bytes(b'x'*6)
            (root/'c.weird').write_bytes(b'x'*1)
            job=ScanJob(root)
            job.run()
            self.assertEqual(job.snapshot()['types'],{'Images':4,'Video':6,'Other':1})
    def test_all_children_listed_before_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for n in 'abc':
                (root/n).mkdir()
                (root/n/'f').write_bytes(b'x')
            job=ScanJob(root)
            seen=[]
            real=job._folder
            def spy(path,row):
                seen.append(len(job.snapshot()['rows']))
                real(path,row)
            job._folder=spy
            job.run()
            self.assertEqual(seen,[3,3,3])
    def test_process_sampler_first_sample_has_no_cpu(self):
        from processes import ProcessSampler
        s=ProcessSampler()
        first=s.sample()
        me=[p for p in first['procs'] if p['pid']==os.getpid()][0]
        self.assertIsNone(me['cpu'])
        second=s.sample()
        me=[p for p in second['procs'] if p['pid']==os.getpid()][0]
        self.assertIsNotNone(me['cpu'])
        self.assertGreater(second['mem_total'],0)
    def test_findings_rules_and_duplicates(self):
        from findings import FindingsJob
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'empty').mkdir()
            (root/'a.dmg').write_bytes(b'a'*50)
            (root/'big.bin').write_bytes(b'b'*200)
            (root/'d1.bin').write_bytes(b'c'*100)
            (root/'d2.bin').write_bytes(b'c'*100)
            (root/'d3.bin').write_bytes(b'z'*100)
            old=time.time()-400*86400
            os.utime(root/'big.bin',(old,old))
            job=FindingsJob(root,large=150,old_days=180,old_min=100,dup_min=10)
            job.run()
            s=job.snapshot()
            by={f['rule']:f for f in s['findings']}
            self.assertEqual([i['path'].endswith('big.bin') for i in by['large']['items']],[True])
            self.assertEqual(len(by['old']['items']),1)
            self.assertEqual(len(by['installers']['items']),1)
            self.assertEqual(len(by['empty']['items']),1)
            self.assertEqual(by['duplicates']['bytes'],100)
            self.assertTrue(by['duplicates']['estimate'])
            self.assertEqual(len(by['duplicates']['groups']),1)
            self.assertEqual(s['status'],'complete')
    def test_permission_failure_is_partial(self):
        with tempfile.TemporaryDirectory() as root:
            denied=Path(root)/'denied'
            denied.mkdir()
            real=os.scandir
            def scandir(path):
                if str(path)==str(denied):
                    raise PermissionError('Access denied')
                return real(path)
            with patch('scanner.os.scandir',side_effect=scandir):
                job=ScanJob(root)
                job.run()
            s=job.snapshot()
            self.assertEqual(s['status'],'partial')
            self.assertEqual(s['rows'][0]['status'],'partial')
            self.assertEqual(s['errors'],1)
    def test_cancel_before_scan(self):
        with tempfile.TemporaryDirectory() as root:
            job=ScanJob(root)
            job.cancelled.set()
            job.run()
            self.assertEqual(job.snapshot()['status'],'cancelled')
    def test_missing_root_and_snapshot_independence(self):
        job=ScanJob('/nonexistent-storage-viewer-fixture')
        job.run()
        state=job.snapshot()
        state['error_samples'].clear()
        self.assertTrue(job.snapshot()['error_samples'])
        self.assertEqual(job.snapshot()['status'],'partial')
    def test_bridge_rejects_unselected_paths(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                Api().start_scan(root)

if __name__=='__main__':
    unittest.main()
