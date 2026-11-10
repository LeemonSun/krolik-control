import copy
import csv
import ctypes
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from winpilot.storage import StorageCenter
from winpilot.memory_test import options,interpret
from winpilot.game_capture import parse_capture
from winpilot import display_advanced as da
from winpilot.audio_routing import AudioRouter
from winpilot.engine import operations
from winpilot.driver_safety import create,verify_manifest

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'Temp';self.root.mkdir();self.s=StorageCenter(SimpleNamespace(demo=False),self.root)
    def file(self,name,old=True):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'data')
        if old:os.utime(p,(time.time()-9*86400,)*2)
        return p
    def test_preview_never_deletes_and_only_old_files_are_candidates(self):
        old=self.file('old');new=self.file('new',False);r=self.s.scan();self.assertEqual(r['files'],1);self.assertTrue(old.exists());self.assertTrue(new.exists())
        job=self.s.consume({'token':r['token'],'confirmed':True});result=self.s.clean(job);self.assertEqual(result['deleted'],1);self.assertTrue(new.exists())
    def test_changed_file_is_skipped(self):
        p=self.file('old');r=self.s.scan();p.write_bytes(b'changed');v=self.s.clean(self.s.consume({'token':r['token'],'confirmed':True}));self.assertEqual(v['skipped'],1);self.assertTrue(p.exists())
    def test_parent_and_file_links_are_never_followed(self):
        outside=Path(self.tmp.name)/'outside';outside.mkdir();f=outside/'keep';f.write_text('x');os.utime(f,(time.time()-9*86400,)*2)
        (self.root/'linked-dir').symlink_to(outside,target_is_directory=True);(self.root/'linked-file').symlink_to(f);r=self.s.scan();self.assertEqual(r['files'],0);self.assertTrue(f.exists())
    def test_replaced_parent_after_preview_is_skipped(self):
        p=self.file('sub/old');r=self.s.scan();sub=self.root/'sub';sub.rename(self.root/'original');sub.symlink_to(self.root/'original',target_is_directory=True)
        result=self.s.clean(self.s.consume({'token':r['token'],'confirmed':True}));self.assertEqual(result['skipped'],1);self.assertTrue(p.exists())
    def test_expiration_confirmation_and_nonce_replay(self):
        self.file('old');r=self.s.scan()
        with self.assertRaises(ValueError):self.s.consume({'token':r['token']})
        self.s.snapshot['expires']=time.monotonic()-1
        with self.assertRaises(ValueError):self.s.consume({'token':r['token'],'confirmed':True})
        r=self.s.scan();self.s.consume({'token':r['token'],'confirmed':True})
        with self.assertRaises(ValueError):self.s.consume({'token':r['token'],'confirmed':True})

class MemoryTests(unittest.TestCase):
    def test_options_are_bounded_and_booleans_rejected(self):
        self.assertEqual(options({}),(256,30))
        for body in ({'mb':True},{'mb':8192},{'seconds':1},{'seconds':True}):
            with self.assertRaises(ValueError):options(body)
    def test_error_pressure_and_incomplete_never_pass(self):
        base={'tested_mb':256,'duration_s':30,'rounds':1,'patterns':5,'errors':0}
        self.assertEqual(interpret(base)[0]['level'],'ok')
        self.assertEqual(interpret({**base,'errors':1})[0]['level'],'problem')
        for r in ({**base,'rounds':0},{**base,'memory_pressure':True}):self.assertEqual(interpret(r)[0]['level'],'warning')
        with self.assertRaises(ValueError):interpret({**base,'errors':float('nan')})
    def test_same_native_pattern_engine_detects_injected_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'memory';source=Path(__file__).parents[1]/'bench/memory.c'
            subprocess.run(['cc','-O2','-Wall','-Wextra','-Werror','-DKC_TESTING',str(source),'-o',str(exe)],check=True,capture_output=True)
            good=subprocess.run([str(exe),'--self-test'],capture_output=True,text=True,timeout=5);bad=subprocess.run([str(exe),'--self-test','--inject-error'],capture_output=True,text=True,timeout=5)
            self.assertEqual(good.returncode,0);self.assertEqual(bad.returncode,1)
            a=json.loads(good.stdout.splitlines()[-1]);b=json.loads(bad.stdout.splitlines()[-1]);self.assertEqual(a['rounds'],1);self.assertEqual(a['patterns'],5);self.assertGreater(b['errors'],0);self.assertEqual(b['rounds'],0)

class FrameTests(unittest.TestCase):
    def file(self,rows):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);p=Path(t.name)/'frames.csv'
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['ProcessID','SwapChainAddress','msBetweenPresents','TimeInSeconds']);w.writeheader();w.writerows(rows)
        return p
    def rows(self,pid=42,chain='A',ms=10,n=100):return [{'ProcessID':pid,'SwapChainAddress':chain,'msBetweenPresents':ms,'TimeInSeconds':i*.01} for i in range(n)]
    def test_process_and_swapchain_isolation(self):
        p=self.file(self.rows()+self.rows(chain='B',ms=100,n=40)+self.rows(pid=7,ms=200,n=300));r=parse_capture(p,42)
        self.assertEqual(r['metrics']['present_fps'],100);self.assertEqual(r['metrics']['captured_frames'],100);self.assertEqual(r['swapchains'],2);self.assertEqual(r['selected_swapchain'],'A')
    def test_invalid_intervals_and_missing_frames_are_not_zero_fps(self):
        p=self.file(self.rows(ms='nan'));self.assertRaises(ValueError,parse_capture,p,42)
        p=self.file(self.rows(n=2));self.assertRaises(ValueError,parse_capture,p,42)
    def test_slow_percent_has_explicit_interval_definition(self):
        rows=self.rows();rows[-1]['msBetweenPresents']=100;p=self.file(rows);m=parse_capture(p,42)['metrics']
        self.assertEqual(m['slowest_percent_fps'],10);self.assertEqual(m['frame_p99_ms'],10)

class DisplayTests(unittest.TestCase):
    def test_fixed_width_ccd_layouts_match_sdk(self):
        for kind,size in [(da.LUID,8),(da.SOURCE,20),(da.TARGET,48),(da.PATH,72),(da.MODE,64),(da.HEADER,20),(da.SOURCE_NAME,84),(da.COLOR2,36),(da.SET_HDR,24)]:self.assertEqual(ctypes.sizeof(kind),size,kind)
    def test_unsupported_hdr_never_calls_setter(self):
        u=SimpleNamespace(DisplayConfigGetDeviceInfo=lambda p:50,DisplayConfigSetDeviceInfo=Mock());p=da.PATH()
        with patch.object(da,'query',return_value=(u,[p],1,[],0)),patch.object(da,'source_name',return_value='display'):
            with self.assertRaises(ValueError):da.hdr_begin('display',True)
        u.DisplayConfigSetDeviceInfo.assert_not_called()
    def test_duplicate_source_does_not_change_hdr_on_wrong_monitor(self):
        u=Mock();p=da.PATH()
        with patch.object(da,'query',return_value=(u,[p,p],2,[],0)),patch.object(da,'source_name',return_value='display'):
            with self.assertRaises(ValueError):da.hdr_begin('display',True)
        u.DisplayConfigSetDeviceInfo.assert_not_called()
    def test_topology_rollback_uses_saved_paths_without_persisting(self):
        u=Mock();u.SetDisplayConfig.return_value=0;paths=(da.PATH*1)();modes=(da.MODE*1)()
        with patch.object(da,'query',return_value=(u,paths,1,modes,1)):
            restore=da.topology_begin('clone');restore(False)
        args=u.SetDisplayConfig.call_args.args;self.assertEqual(args[0],1);self.assertIs(args[1],paths);self.assertEqual(args[-1],0x20|0x80)

class BackupTests(unittest.TestCase):
    def test_export_failure_removes_partial_copy(self):
        with tempfile.TemporaryDirectory() as d,patch('winpilot.care_windows.driver_root',return_value=Path(d)),patch.dict('os.environ',{'SystemRoot':'C:/Windows'}):
            b=SimpleNamespace(run=Mock(side_effect=OSError('export failed')))
            with self.assertRaises(OSError):create(b)
            self.assertEqual(list(Path(d).iterdir()),[])
    def test_tampered_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as d,patch('winpilot.care_windows.driver_root',return_value=Path(d)),patch.dict('os.environ',{'SystemRoot':'C:/Windows'}):
            def export(args,**kwargs):(Path(args[-1])/'driver.inf').write_text('original')
            r=create(SimpleNamespace(run=export));p=Path(r['path']);verify_manifest(p);(p/'driver.inf').write_text('tampered')
            with self.assertRaises(ValueError):verify_manifest(p)
    def test_driver_update_has_backup_before_any_update(self):
        updates=[{'id':'a','revision':1,'driver':True,'name':'Driver'},{'id':'b','revision':1,'driver':False,'name':'Windows'}]
        ops=operations({'updates':['a','b']},{},updates);self.assertEqual([r['kind'] for r in ops],['driver_safety','update','update'])
        self.assertEqual([r['kind'] for r in operations({'updates':['b']},{},updates)],['update'])

class AudioRoleTests(unittest.TestCase):
    def test_demo_default_role_requires_confirmation_and_preserves_other_roles(self):
        with tempfile.TemporaryDirectory() as d:
            endpoints=[{'id':'a','flow':0,'default':True,'default_roles':[0,1,2]},{'id':'b','flow':0,'default':False,'default_roles':[]}]
            app=SimpleNamespace(demo=True,info={'endpoints':endpoints},backend=SimpleNamespace(info={}),lock=threading.RLock(),data_revision=0);router=AudioRouter(app,d)
            with self.assertRaises(ValueError):router.apply({'id':'b','role':2,'confirmed':True})
            router.apply({'id':'b','role':2,'confirmed':True,'experimental_ack':True})
            self.assertEqual(endpoints[0]['default_roles'],[0,1]);self.assertEqual(endpoints[1]['default_roles'],[2]);self.assertTrue(endpoints[0]['default']);self.assertEqual(json.loads(router.path.read_text())['before'],'a')

class ReleaseReturnTests(unittest.TestCase):
    def router(self,d):
        endpoints=[{'id':'a','flow':0,'default':True,'default_roles':[0,1,2]},{'id':'b','flow':0,'default':False,'default_roles':[]}]
        app=SimpleNamespace(demo=True,info={'endpoints':endpoints},backend=SimpleNamespace(info={}),lock=threading.RLock(),data_revision=0)
        return AudioRouter(app,d),endpoints
    def test_audio_undo_preserves_roles_and_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            r,e=self.router(d);r.apply({'id':'b','role':2,'confirmed':True,'experimental_ack':True})
            r.undo({'confirmed':True,'experimental_ack':True});self.assertEqual(e[0]['default_roles'],[0,1,2]);self.assertEqual(e[1]['default_roles'],[])
            with self.assertRaises(ValueError):r.undo({'confirmed':True,'experimental_ack':True})
    def test_audio_undo_does_not_overwrite_external_changes_or_disconnected_device(self):
        for disconnected in (False,True):
            with tempfile.TemporaryDirectory() as d:
                r,e=self.router(d);r.apply({'id':'b','role':2,'confirmed':True,'experimental_ack':True})
                if disconnected:e.pop(0)
                else:e[0]['default_roles']=[0,1,2];e[1]['default_roles']=[]
                before=copy.deepcopy(e)
                with self.assertRaises(ValueError):r.undo({'confirmed':True,'experimental_ack':True})
                self.assertEqual(e,before)
    def test_backup_unlisted_file_and_nonstring_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);f=p/'driver.inf';f.write_text('driver')
            m={'complete':True,'files':[{'path':'driver.inf','bytes':6,'sha256':__import__('hashlib').sha256(f.read_bytes()).hexdigest()}]}
            manifest=p/'KrolikControl-backup.json';manifest.write_text(json.dumps(m));verify_manifest(p)
            (p/'extra.inf').write_text('extra')
            with self.assertRaises(ValueError):verify_manifest(p)
            (p/'extra.inf').unlink();m['files'][0]['path']={};manifest.write_text(json.dumps(m))
            with self.assertRaises(ValueError):verify_manifest(p)

class VerificationEvidenceTests(unittest.TestCase):
    def test_existing_old_program_is_not_a_confirmed_upgrade(self):
        from winpilot.windows import Windows
        backend=Windows();backend.local_programs=lambda:[{'id':'Mozilla.Firefox','installed':True,'version':'1.0'}]
        op={'kind':'upgrade','key':'Mozilla.Firefox','value':'','expected_version':'2.0'}
        self.assertEqual(backend.verify_operation(op)['status'],'unverified')
        op['installer_reboot']=True;self.assertEqual(backend.verify_operation(op)['status'],'deferred')
        backend.local_programs=lambda:[{'id':'Mozilla.Firefox','installed':True,'version':'2.0'}]
        self.assertEqual(backend.verify_operation(op)['status'],'confirmed')
    def test_time_zone_snapshot_is_checked_and_readback_must_match(self):
        from winpilot.recovery import checked_undo
        from winpilot.windows import Windows
        entry={'kind':'setting','key':'time_zone','value':'Russian Standard Time'}
        self.assertEqual(checked_undo([entry]),[entry])
        for bad in ('UTC;Remove-Item',True,'x'*151):
            with self.assertRaises(ValueError):checked_undo([{**entry,'value':bad}])
        backend=Windows();backend.psjson=lambda *a,**k:'UTC'
        self.assertNotEqual(backend.verify_operation({'kind':'setting','key':'time_zone','value':'Russian Standard Time'})['status'],'confirmed')
        self.assertEqual(backend.verify_operation({'kind':'setting','key':'time_zone','value':'UTC'})['status'],'confirmed')
    def test_failed_driver_backup_prevents_update_execution(self):
        from winpilot.engine import Engine
        from winpilot.demo import Demo
        with tempfile.TemporaryDirectory() as d:
            b=Demo();b.info['admin']=True;b.install_update=Mock();e=Engine(b,d,False);b.display_guard.restore_pending=lambda:None
            e._apply=Mock(side_effect=[ValueError('disk full')])
            e.start({'updates':['driver']},b.info,[{'id':'driver','name':'GPU','revision':1,'driver':True}])
            deadline=time.monotonic()+3
            while e.snapshot()['running'] and time.monotonic()<deadline:time.sleep(.01)
            result=e.snapshot();self.assertFalse(result['running']);self.assertEqual(e._apply.call_count,1)
            self.assertEqual([r['status'] for r in result['items']],['error','skipped']);b.install_update.assert_not_called()

class CaptureCancellationTests(unittest.TestCase):
    def test_already_killed_cancelled_process_still_closes_its_session(self):
        from winpilot import game_capture as gc
        from winpilot.care import Cancelled
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'winpilot').mkdir();helper=root/'PresentMon-2.6.0-x64.exe';helper.write_bytes(b'helper')
            c=SimpleNamespace(directory=root,lock=threading.RLock(),cancel=threading.Event(),process=None)
            c.app=SimpleNamespace(data={'game_processes':[{'id':42,'name':'game','started':'same'}]},backend=SimpleNamespace(psjson=lambda *a,**k:{'name':'game','started':'same'}),engine=Mock(),lock=threading.RLock(),info={})
            proc=Mock();proc.poll.return_value=-9;proc.returncode=-9
            def launch(*a,**k):c.cancel.set();return proc
            sensor=Mock();sensor.value={}
            with patch.object(gc,'__file__',str(root/'winpilot/game_capture.py')),patch.object(gc,'PRESENTMON_SHA',__import__('hashlib').sha256(b'helper').hexdigest()),patch.object(gc.subprocess,'Popen',side_effect=launch),patch.object(gc.subprocess,'run') as cleanup,patch('winpilot.pc.PcCenter',return_value=sensor):
                with self.assertRaises(Cancelled):gc.run(c,{'pid':42,'seconds':30})
                args=cleanup.call_args.args[0];self.assertEqual(args[0],str(helper));self.assertIn('--terminate_existing_session',args);self.assertTrue(args[args.index('--session_name')+1].startswith('Krolik-'))
                sensor.close.assert_called_once();self.assertIsNone(c.process)
