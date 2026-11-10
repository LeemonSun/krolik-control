import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from winpilot.workspace import Workspace, saved_plan, atomic_json
from winpilot.engine import Engine
from winpilot.demo import Demo, INFO
from winpilot.windows import REG
from winpilot.recovery import checked_undo
from winpilot.server import Application

class WorkspaceTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.w=Workspace(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def save(self,**changes):return self.w.save({**self.w.value,**changes})
    def test_reopen_preserves_choices(self):
        self.save(draft={'settings':{'theme':'light'}},favorites=['setting:theme'],theme='light',mode='all')
        new=Workspace(self.tmp.name)
        self.assertEqual(new.value['draft']['settings']['theme'],'light');self.assertEqual(new.value['favorites'],['setting:theme']);self.assertEqual(new.value['theme'],'light')
    def test_incomplete_dns_can_be_staged(self):self.save(draft={'settings':{'dns':'google'},'adapter':None})
    def test_profile_can_be_saved_before_hardware_discovery(self):
        self.save(profiles=[{'name':'Мой ПК','plan':{'displays':[{'id':'another-display','mode':'1920x1080@144','orientation':0}]}}])
    def test_arbitrary_command_rejected(self):
        with self.assertRaises(ValueError):self.save(draft={'command':'powershell.exe'})
    def test_invalid_setting_value(self):
        with self.assertRaises(ValueError):self.save(draft={'settings':{'mouse_speed':'999'}})
    def test_unknown_favorite(self):
        with self.assertRaises(ValueError):self.save(favorites=['action:execute-command'])
    def test_invalid_save_does_not_overwrite(self):
        self.save(theme='light')
        with self.assertRaises(ValueError):self.save(theme='evil')
        self.assertEqual(Workspace(self.tmp.name).value['theme'],'light')
    def test_duplicate_profile_names(self):
        with self.assertRaises(ValueError):self.save(profiles=[{'name':'PC','plan':{}},{'name':'pc','plan':{}}])
    def test_profile_limit(self):
        with self.assertRaises(ValueError):self.save(profiles=[{'name':str(i),'plan':{}} for i in range(21)])
    def test_wrong_display_shape(self):
        with self.assertRaises(ValueError):saved_plan({'displays':[{'id':'x','mode':'1920x1080@144;calc','orientation':0}]})
    def test_reject_update_query_injection(self):
        with self.assertRaises(ValueError):saved_plan({'updates':["x' or IsInstalled=0"]})
    def test_clear_only_successful_matching_settings(self):
        self.save(draft={'settings':{'theme':'light','extensions':'on'},'apps':['Mozilla.Firefox']})
        self.w.clear_successes([{'status':'success','kind':'setting','key':'theme','value':'light'},{'status':'error','kind':'setting','key':'extensions','value':'on'}])
        self.assertNotIn('theme',self.w.value['draft']['settings']);self.assertEqual(self.w.value['draft']['settings']['extensions'],'on');self.assertEqual(self.w.value['draft']['apps'],['Mozilla.Firefox'])
    def test_corrupt_workspace_not_executed(self):
        self.w.path.write_text('{bad',encoding='utf-8');new=Workspace(self.tmp.name)
        self.assertIsNotNone(new.warning);self.assertEqual(new.value['draft'],{})
    def test_favorites_deduplicated(self):self.assertEqual(self.save(favorites=['setting:theme']*2)['favorites'],['setting:theme'])

class RecoveryTests(unittest.TestCase):
    def valid(self):
        path,name,_=REG['theme'][0]
        return [{'kind':'registry','values':[{'path':path,'name':name,'exists':True,'kind':4,'value':0}]}]
    def test_reject_registry_outside_allowlist(self):
        values=self.valid();values[0]['values'][0]['path']='Software\\Unrelated'
        with self.assertRaises(ValueError):checked_undo(values)
    def test_reject_shell_in_power_setting(self):
        with self.assertRaises(ValueError):checked_undo([{'kind':'setting','key':'power_plan','value':'calc.exe'}])
    def test_reject_wrong_dns_addresses(self):
        with self.assertRaises(ValueError):checked_undo([{'kind':'dns','adapter':1,'value':{'auto':False,'servers':['not-an-ip']}}])
    def test_accept_legitimate_snapshot(self):self.assertEqual(checked_undo(self.valid()),self.valid())
    def test_restore_available_after_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=Demo();value=[0];engine=Engine(backend,directory,False)
            def wait(e):
                end=time.monotonic()+3
                while e.snapshot()['running'] and time.monotonic()<end:time.sleep(.005)
                self.assertFalse(e.snapshot()['running'])
            with patch.object(backend,'reg_snapshot',create=True,return_value=self.valid()[0]['values']),patch.object(backend,'apply_setting',create=True,side_effect=lambda *a:value.__setitem__(0,1)):
                engine.start({'settings':{'theme':'light'}},INFO,[]);wait(engine)
            restarted=Engine(backend,directory,False);self.assertTrue(restarted.snapshot()['can_undo']);self.assertFalse(restarted.snapshot()['running'])
            with patch.object(backend,'restore_registry',create=True,side_effect=lambda rows:value.__setitem__(0,rows[0]['value'])):
                restarted.start_undo();wait(restarted)
            self.assertEqual(value[0],0);self.assertFalse(Engine(backend,directory,False).snapshot()['can_undo'])
    def test_bad_backup_disables_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            atomic_json(Path(directory)/'last-settings-backup.json',[{'kind':'shell','value':'calc.exe'}])
            engine=Engine(Demo(),directory)
            self.assertIsNotNone(engine.recovery_warning);self.assertFalse(engine.snapshot()['can_undo'])
    def test_interrupted_history_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            row={'time':'2026-10-17T20:00:00+03:00','index':0,'title':'Установка','status':'running','message':''}
            (Path(directory)/'apply-1.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
            engine=Engine(Demo(),directory,True)
            self.assertTrue(engine.history[0]['interrupted']);self.assertFalse(engine.snapshot()['running'])

class WorkspaceAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Application(Demo(),Path(__file__).parents[1]/'ui',self.tmp.name,True);self.app.info=copy.deepcopy(INFO)
    def tearDown(self):self.tmp.cleanup()
    def test_reject_stale_save_revision(self):
        payload={'revision':0,'workspace':self.app.workspace.value}
        self.app.post('/api/workspace',payload)
        with self.assertRaises(ValueError):self.app.post('/api/workspace',payload)
    def test_catalog_uris_are_allowlisted(self):
        from winpilot.catalog import LINKS
        for a in self.app.catalog():
            if a['kind']=='windows':self.assertIn(a['link'],LINKS)
    def test_demo_never_requests_uac(self):
        with patch.object(self.app.backend,'elevate',create=True,side_effect=AssertionError('UAC should not run')):
            self.assertFalse(self.app.post('/api/elevate',{})['restarting'])
    def test_cancelled_elevation_does_not_close_app(self):
        self.app.demo=False
        with patch.object(self.app.backend,'elevate',create=True,side_effect=RuntimeError('cancelled')):
            with self.assertRaisesRegex(RuntimeError,'cancelled'):self.app.post('/api/elevate',{})
        self.assertIsNone(self.app.http)
    def test_profiles_validated_without_mutations(self):
        self.app.post('/api/profile/validate',{'settings':{'theme':'light'}})
        self.assertFalse(self.app.engine.snapshot()['running']);self.assertEqual(self.app.engine.snapshot()['items'],[])

if __name__=='__main__':unittest.main()
