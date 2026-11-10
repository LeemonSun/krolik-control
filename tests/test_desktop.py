import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from winpilot.demo import Demo,INFO
from winpilot.engine import Engine,validate_plan
from winpilot.server import Application
from winpilot.workspace import Workspace,saved_plan,ui_preferences,atomic_json
from winpilot.instance import InstanceLock
from winpilot.display_layout import validate_layout,apply,restore
from winpilot.native import DEVMODE
from winpilot.audio_tools import tone_samples


def wait_engine(engine):
    end=time.monotonic()+4
    while engine.snapshot()['running'] and time.monotonic()<end:time.sleep(.01)
    assert not engine.snapshot()['running']

class WorkspaceReliabilityTests(unittest.TestCase):
    def test_conflicting_writers_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Workspace(d),Workspace(d);a.save({'draft':{'settings':{'theme':'dark'}}})
            with self.assertRaisesRegex(ValueError,'другом окне'):b.save({'draft':{'settings':{'theme':'light'}}})
            self.assertEqual(json.loads((Path(d)/'workspace.json').read_text())['draft']['settings']['theme'],'dark')
    def test_atomic_replace_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';atomic_json(path,{'before':1})
            with patch('os.replace',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):atomic_json(path,{'after':2})
            self.assertEqual(json.loads(path.read_text()),{'before':1});self.assertEqual(list(Path(d).glob('*.tmp')),[])
    def test_real_process_lock_excludes_second_writer(self):
        with tempfile.TemporaryDirectory() as d:
            lock=InstanceLock(d);self.assertTrue(lock.acquire())
            code="from winpilot.instance import InstanceLock;import sys;x=InstanceLock(sys.argv[1]);sys.exit(3 if x.acquire() else 0)"
            r=subprocess.run([sys.executable,'-c',code,d],cwd=Path(__file__).parents[1],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr);lock.close();second=InstanceLock(d);self.assertTrue(second.acquire());second.close()
    def test_ui_state_round_trip(self):
        value={'zoom':150,'density':'compact','last_page':'monitor','history':{'entries':['overview','monitor'],'index':1},'views':{'monitor':{'scroll':520,'monitor':'DISPLAY1','expanded':['modes']}},'driver_targets':['PCI\\VID_1234'],'window':{'left':-1200,'top':0,'width':1240,'height':860}}
        with tempfile.TemporaryDirectory() as d:
            Workspace(d).save({'ui':value,'theme':'system'});w=Workspace(d);self.assertEqual(w.value['ui'],value);self.assertEqual(w.value['theme'],'system')
    def test_invalid_preferences_rejected(self):
        for value in [{'zoom':True},{'zoom':200},{'history':{'entries':['evil'],'index':0}},{'window':{'width':0}},{'views':{'monitor':{'script':'bad'}}}]:
            with self.subTest(value=value),self.assertRaises(ValueError):ui_preferences(value)

class NewPlanTests(unittest.TestCase):
    def setUp(self):
        self.backend=Demo();self.info=copy.deepcopy(INFO);self.info['programs']=self.backend.programs();self.info['startup']=self.backend.startup()
    def check(self,p):return validate_plan(p,self.info,[],demo=True)
    def test_known_upgrade_allowed(self):self.check({'upgrades':['Mozilla.Firefox']})
    def test_unadvertised_upgrade_rejected(self):
        with self.assertRaises(ValueError):self.check({'upgrades':['Valve.Steam']})
    def test_install_and_upgrade_conflict(self):
        with self.assertRaises(ValueError):self.check({'apps':['Mozilla.Firefox'],'upgrades':['Mozilla.Firefox']})
    def test_startup_cannot_add_arbitrary_command(self):
        for p in [{'startup':[{'id':'a'*64,'enabled':False,'command':'calc.exe'}]},{'startup':[{'id':'b'*64,'enabled':False}]},{'startup':[{'id':'a'*64,'enabled':'false'}]}]:
            with self.subTest(p=p),self.assertRaises(ValueError):self.check(p)
    def test_known_startup_allowed(self):self.check({'startup':[{'id':'a'*64,'enabled':False}]})
    def test_custom_languages_preserved_in_saved_plan(self):
        p={'languages':['de-DE','ru-RU','en-US']};self.assertEqual(saved_plan(p),p);self.check(p)
    def test_languages_duplicate_and_preset_conflict(self):
        for p in [{'languages':['de-DE','de-DE']},{'languages':['de-DE;calc.exe']},{'languages':['de-DE'],'settings':{'layouts':'ru-en'}}]:
            with self.subTest(p=p),self.assertRaises(ValueError):self.check(p)
    def test_saved_layout_does_not_require_connected_hardware(self):
        p={'layout':[{'id':'disconnected','x':0,'y':0,'primary':True}]};self.assertEqual(saved_plan(p),p)
    def test_layout_cannot_overlap_or_detach(self):
        base=[{'id':'demo-display-1','x':0,'y':0,'primary':True},{'id':'demo-display-2','x':2560,'y':0,'primary':False}]
        validate_layout(base,self.info['displays'])
        for x in [0,3000]:
            bad=copy.deepcopy(base);bad[1]['x']=x
            with self.assertRaises(ValueError):validate_layout(bad,self.info['displays'])
    def test_layout_primary_must_be_origin(self):
        with self.assertRaises(ValueError):validate_layout([{'id':'demo-display-1','x':0,'y':0,'primary':False},{'id':'demo-display-2','x':2560,'y':0,'primary':True}],self.info['displays'])

class EngineReliabilityTests(unittest.TestCase):
    def test_restore_point_failure_stops_later_operations(self):
        with tempfile.TemporaryDirectory() as d:
            b=Demo();e=Engine(b,d,False)
            with patch.object(b,'restore_point',create=True,side_effect=OSError('disabled')),patch.object(b,'install_app',create=True) as installer:
                info={**INFO,'admin':True};e.start({'restore_point':True,'apps':['Mozilla.Firefox']},info,[]);wait_engine(e)
                installer.assert_not_called();self.assertEqual([r['status'] for r in e.snapshot()['items']],['error','skipped'])
    def test_result_readback_rejection_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            b=Demo();e=Engine(b,d,False)
            with patch.object(b,'install_app',create=True,return_value='done'),patch.object(b,'verify_operation',create=True,return_value={'status':'rejected','message':'wrong result'}):
                e.start({'apps':['Mozilla.Firefox']},INFO,[]);wait_engine(e);self.assertEqual(e.snapshot()['items'][0]['status'],'error')
    def test_log_failure_prevents_execution(self):
        with tempfile.TemporaryDirectory() as d:
            b=Demo();e=Engine(b,d,False)
            with patch.object(e,'record',return_value=False),patch.object(b,'install_app',create=True) as installer:
                with self.assertRaises(OSError):e.start({'apps':['Mozilla.Firefox']},INFO,[])
                installer.assert_not_called();self.assertFalse(e.snapshot()['running'])
    def test_save_error_visible_and_retry_clears_without_reapplying(self):
        with tempfile.TemporaryDirectory() as d:
            app=Application(Demo(),Path(__file__).parents[1]/'ui',d,True);app.info=copy.deepcopy(INFO)
            with patch.object(app.workspace,'clear_successes',side_effect=OSError('save failed')):
                app.post('/api/apply',{'settings':{'extensions':'on'}});wait_engine(app.engine)
            self.assertIn('save failed',app.engine.snapshot()['persistence_error']);app.engine.retry_persistence();self.assertNotIn('persistence_error',app.engine.snapshot());self.assertEqual(app.workspace.value['draft'].get('settings',{}),{})
    def test_undo_order_blocks_older_group(self):
        with tempfile.TemporaryDirectory() as d:
            e=Engine(Demo(),d,True);e.undo_groups=[{'id':'old','entries':[{'kind':'brightness','key':'x','value':40}]},{'id':'new','entries':[{'kind':'brightness','key':'x','value':80}]}]
            with self.assertRaisesRegex(ValueError,'более поздние'):e.undo_entries('old')
    def test_unconfirmed_undo_keeps_backup(self):
        with tempfile.TemporaryDirectory() as d:
            b=Demo();e=Engine(b,d,False);e.undo_groups=[{'id':'latest','time':'2026-10-18','entries':[{'kind':'brightness','key':'screen','value':40}]}];e.undo=e.undo_groups[0]['entries']
            with patch.object(b,'brightness',create=True),patch.object(b,'verify_undo',create=True,return_value={'status':'unverified','message':'offline'}):
                e.start_undo();wait_engine(e)
            self.assertEqual(len(e.undo),1);self.assertEqual(e.snapshot()['items'][0]['status'],'error')
    def test_sound_tone_bounded_and_fades_edges(self):
        import struct
        data=tone_samples(4800,2,48000,32,3);values=struct.unpack('<'+str(len(data)//4)+'f',data)
        self.assertLessEqual(max(map(abs,values)),.061);self.assertEqual(values[:2],(0,0));self.assertEqual(values[-2:],(0,0))
    def test_audio_wrong_endpoint_flow_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            app=Application(Demo(),Path(__file__).parents[1]/'ui',d,True);app.info=copy.deepcopy(INFO)
            with self.assertRaises(ValueError):app.post('/api/audio/test',{'id':'demo-microphone'})

if __name__=='__main__':unittest.main()

class LayoutTransactionTests(unittest.TestCase):
    def test_temporary_layout_does_not_persist_until_confirmation(self):
        import ctypes as C
        from winpilot import native
        rows=[{'id':'demo-display-1','x':-2560,'y':0,'primary':False},{'id':'demo-display-2','x':0,'y':0,'primary':True}]
        calls=[]
        class API:
            def EnumDisplaySettingsW(self,ident,index,pointer):
                dm=C.cast(pointer,C.POINTER(DEVMODE)).contents;d=next(d for d in INFO['displays'] if d['id']==ident)
                dm.width,dm.height=map(int,d['current'].split('@')[0].split('x'));dm.hz=60;dm.bpp=32;dm.display.position.x=d['x'];dm.display.position.y=d['y'];return True
            def ChangeDisplaySettingsExW(self,ident,dm,hwnd,flags,param):calls.append(flags);return 0
        guard=native.DisplayGuard()
        with patch.object(native,'user32',return_value=API()),patch.object(native,'enumerate_displays',return_value=copy.deepcopy(INFO['displays'])):
            ident=guard.apply_layout(rows)
            self.assertFalse(any(flags&1 for flags in calls))
            self.assertTrue(guard.resolve(ident,True));self.assertTrue(any(flags&0x10000001==0x10000001 for flags in calls));self.assertTrue(guard.wait(ident))
    def test_unconfirmed_layout_restores_without_registry_writes(self):
        import ctypes as C
        from winpilot import native
        calls=[]
        class API:
            def EnumDisplaySettingsW(self,ident,index,pointer):
                dm=C.cast(pointer,C.POINTER(DEVMODE)).contents;dm.width=100;dm.height=100;dm.bpp=32;return True
            def ChangeDisplaySettingsExW(self,ident,dm,hwnd,flags,param):calls.append(flags);return 0
        displays=[{'id':'A','primary':True,'current':'100x100@60'}]
        with patch.object(native,'user32',return_value=API()),patch.object(native,'enumerate_displays',return_value=displays):
            guard=native.DisplayGuard();ident=guard.apply_layout([{'id':'A','x':0,'y':0,'primary':True}]);self.assertTrue(guard.resolve(ident,False));self.assertFalse(guard.wait(ident));self.assertFalse(any(flags&1 for flags in calls))

class StartupFilesTests(unittest.TestCase):
    def test_disabled_file_is_outside_startup_and_can_be_restored(self):
        from winpilot.maintenance import startup_directory,startup_inventory,set_startup
        import types
        fake=types.SimpleNamespace(HKEY_CURRENT_USER=1,HKEY_LOCAL_MACHINE=2,OpenKey=lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError()))
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'APPDATA':str(Path(d)/'Roaming')}),patch.dict(sys.modules,{'winreg':fake}):
            backend=Demo();backend.directory=Path(d)/'profiles';backend.directory.mkdir();folder=startup_directory();folder.mkdir(parents=True);file=folder/'Example.lnk';file.write_bytes(b'example')
            row=startup_inventory(backend)[0];set_startup(backend,row['id'],False)
            self.assertFalse(file.exists());self.assertEqual(list(folder.iterdir()),[]);self.assertEqual((backend.directory/'disabled-startup-files/Example.lnk').read_bytes(),b'example')
            set_startup(backend,row['id'],True);self.assertEqual(file.read_bytes(),b'example');self.assertEqual(json.loads((backend.directory/'disabled-startup.json').read_text()),[])

class RotationReadbackTests(unittest.TestCase):
    def test_portrait_readback_compares_rotated_dimensions(self):
        from winpilot.windows import Windows
        with patch('winpilot.native.enumerate_displays',return_value=[{'id':'A','current':'1080x1920@144','orientation':1}]):
            result=Windows().verify_operation({'kind':'display','key':'A','value':'1920x1080@144','orientation':1,'original_orientation':0})
        self.assertEqual(result['status'],'confirmed')
