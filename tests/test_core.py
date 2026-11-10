import copy
import json
import os
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from winpilot.demo import Demo, INFO
from winpilot.engine import Engine, operations, validate_plan
from winpilot.server import Application, create_server
from winpilot.windows import Windows, REG

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.info=copy.deepcopy(INFO); self.info['admin']=True
        self.updates=[{'id':'update-1','revision':1,'name':'Test'}]
    def check(self,p): return validate_plan(p,self.info,self.updates)
    def test_valid(self): self.check({'settings':{'theme':'light','mouse_speed':'20'},'apps':['Mozilla.Firefox']})
    def test_unknown_setting(self):
        with self.assertRaises(ValueError): self.check({'settings':{'shell':'calc.exe'}})
    def test_command_injection(self):
        with self.assertRaises(ValueError): self.check({'settings':{'screen_ac':'1; calc.exe'}})
    def test_unknown_top_field(self):
        with self.assertRaises(ValueError): self.check({'command':'calc.exe'})
    def test_unknown_app(self):
        with self.assertRaises(ValueError): self.check({'apps':['evil.exe']})
    def test_duplicate_app(self):
        with self.assertRaises(ValueError): self.check({'apps':['Mozilla.Firefox']*2})
    def test_no_winget(self):
        self.info['winget']=False
        self.check({'apps':['Mozilla.Firefox']})
        self.assertEqual(operations({'apps':['Mozilla.Firefox']},self.info,[])[0]['kind'],'package_manager')
    def test_update_requires_discovery(self):
        with self.assertRaises(ValueError): self.check({'updates':['not-scanned']})
    def test_update_valid(self): self.check({'updates':['update-1']})
    def test_admin(self):
        self.info['admin']=False
        with self.assertRaises(ValueError): self.check({'updates':['update-1']})
    def test_demo_admin(self):
        self.info['admin']=False
        validate_plan({'updates':['update-1']},self.info,self.updates,demo=True)
    def test_no_battery(self):
        with self.assertRaises(ValueError): self.check({'settings':{'screen_dc':'10'}})
    def test_taskbar_windows10(self):
        self.info['build']='19045'
        with self.assertRaises(ValueError): self.check({'settings':{'taskbar_align':'center'}})
    def test_dns_no_adapter(self):
        with self.assertRaises(ValueError): self.check({'settings':{'dns':'google'}})
    def test_dns_wrong_adapter(self):
        with self.assertRaises(ValueError): self.check({'settings':{'dns':'google'},'adapter':True})
    def test_dns(self): self.check({'settings':{'dns':'google'},'adapter':8})
    def display(self,**kw): return {'id':'demo-display-1','mode':'2560x1440@180','orientation':0,**kw}
    def test_display(self): self.check({'displays':[self.display()]})
    def test_display_unsupported_rate(self):
        with self.assertRaises(ValueError): self.check({'displays':[self.display(mode='1920x1080@180')]})
    def test_display_duplicate(self):
        with self.assertRaises(ValueError): self.check({'displays':[self.display(),self.display()]})
    def test_display_bool_orientation(self):
        with self.assertRaises(ValueError): self.check({'displays':[self.display(orientation=True)]})
    def test_display_disconnected(self):
        with self.assertRaises(ValueError): self.check({'displays':[self.display(id='missing')]})
    def test_brightness_unavailable(self):
        with self.assertRaises(ValueError): self.check({'brightness':[{'id':'external','value':50}]})
    def test_version(self):
        with self.assertRaises(ValueError): self.check({'version':True})
    def test_no_mutation(self):
        p={'settings':{'theme':'dark'}}; result=self.check(p); result['settings']['theme']='light'
        self.assertEqual(p['settings']['theme'],'dark')
    def test_order(self):
        p={'settings':{'sleep_ac':'10','power_plan':self.info['power_plans'][0]['id']},'updates':['update-1'],'displays':[self.display()]}
        ops=operations(p,self.info,self.updates)
        self.assertEqual(ops[0]['key'],'power_plan'); self.assertEqual(ops[-1]['kind'],'display')

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.engine=Engine(Demo(),self.tmp.name,True)
    def tearDown(self): self.tmp.cleanup()
    def wait(self):
        deadline=time.monotonic()+5
        while self.engine.snapshot()['running'] and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(self.engine.snapshot()['running'])
    def test_demo_never_modifies(self):
        with patch.object(self.engine.backend,'install_app',create=True,side_effect=AssertionError('must not call')):
            self.engine.start({'settings':{'theme':'light'},'apps':['Mozilla.Firefox']},copy.deepcopy(INFO),[]); self.wait()
        self.assertTrue(all(i['status']=='success' for i in self.engine.snapshot()['items']))
        self.assertEqual(self.engine.backend.info['settings']['theme'],'light')
        self.assertEqual(INFO['settings']['theme'],'dark')
    def test_empty(self):
        with self.assertRaises(ValueError): self.engine.start({},INFO,[])
    def test_double_start(self):
        self.engine.start({'apps':['Mozilla.Firefox','Google.Chrome']},INFO,[])
        with self.assertRaises(ValueError): self.engine.start({'apps':['Mozilla.Firefox']},INFO,[])
        self.wait()
    def test_cancel(self):
        self.engine.start({'apps':['Mozilla.Firefox','Google.Chrome']},INFO,[]); self.engine.cancel.set();self.wait()
        self.assertTrue(any(i['status']=='skipped' for i in self.engine.snapshot()['items']))
    def test_log_records_result(self):
        self.engine.start({'apps':['Mozilla.Firefox']},INFO,[]);self.wait()
        records=[json.loads(r) for r in Path(self.engine.snapshot()['log']).read_text().splitlines()]
        self.assertEqual(records[-1]['status'],'success')
    def test_error_does_not_report_success(self):
        self.engine.demo=False; info=copy.deepcopy(INFO);info['admin']=True
        with patch.object(self.engine,'_apply',side_effect=[RuntimeError('driver failed'),None]):
            self.engine.start({'apps':['Mozilla.Firefox','Google.Chrome']},info,[]);self.wait()
        self.assertEqual([i['status'] for i in self.engine.snapshot()['items']],['error','success'])
    def test_power_failure_skips_timeouts(self):
        self.engine.demo=False;info=copy.deepcopy(INFO);info['admin']=True
        with patch.object(self.engine,'_apply',side_effect=RuntimeError('power fail')):
            self.engine.start({'settings':{'power_plan':info['power_plans'][0]['id'],'sleep_ac':'10'}},info,[]);self.wait()
        self.assertEqual([i['status'] for i in self.engine.snapshot()['items']],['error','skipped'])
    def test_registry_backup_precedes_write(self):
        self.engine.demo=False;events=[]
        with patch.object(self.engine.backend,'reg_snapshot',create=True,side_effect=lambda k:events.append('snapshot') or []),patch.object(self.engine.backend,'apply_setting',create=True,side_effect=lambda *a:events.append('write')):
            self.engine.start({'settings':{'theme':'light'}},INFO,[]);self.wait()
        self.assertEqual(events,['snapshot','write']);self.assertTrue(self.engine.snapshot()['can_undo'])

class WindowsAdapterTests(unittest.TestCase):
    def test_driver_singleton_normalized(self):
        with patch.object(Windows,'psjson',return_value={'id':'one'}): self.assertEqual(Windows().drivers(),[{'id':'one'}])
    def test_update_singleton_normalized(self):
        with patch.object(Windows,'psjson',return_value={'id':'one'}): self.assertEqual(Windows().search_updates('Driver'),[{'id':'one'}])
    def test_activation_singleton_normalized(self):
        with patch.object(Windows,'psjson',return_value={'Name':'Windows'}): self.assertEqual(Windows().activation(),[{'Name':'Windows'}])
    def test_invalid_update_kind(self):
        with self.assertRaises(ValueError): Windows().search_updates("Driver';calc")
    def test_ps_payload_is_data(self):
        win=Windows();captured=[]
        def run(args,timeout):
            script=Path(args[-1]).read_text(encoding='utf-8-sig');captured.append(script);return ''
        with patch.object(win,'run',side_effect=run): win.ps('$p.foo',{'foo':"'; calc.exe; #"})
        self.assertNotIn('calc.exe',captured[0]);self.assertIn('FromBase64String',captured[0])
    def test_registry_unknown_key(self):
        with self.assertRaises((KeyError,ModuleNotFoundError)): Windows().set_registry('shell','value')

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.app=Application(Demo(),Path(__file__).parents[1]/'ui',cls.tmp.name,True);cls.app.info=copy.deepcopy(INFO)
        cls.server=create_server(cls.app);cls.port=cls.server.server_port
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
    def req(self,path,body=None,auth=True,**headers):
        c=HTTPConnection('127.0.0.1',self.port,timeout=5)
        h={'Content-Type':'application/json',**headers}
        if auth:h['X-WinPilot-Token']=self.app.token
        data=json.dumps(body) if body is not None else None
        c.request('POST' if body is not None else 'GET',path,data,h);r=c.getresponse();raw=r.read();status=r.status;c.close();return status,raw
    def test_static(self):
        status,raw=self.req('/');self.assertEqual(status,200);self.assertIn('Krolik Control'.encode(),raw)
    def test_state_auth(self): self.assertEqual(self.req('/api/state',auth=False)[0],403)
    def test_state_authorized(self): self.assertEqual(self.req('/api/state')[0],200)
    def test_close_acknowledges_before_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Application(Demo(),Path(__file__).parents[1]/'ui',directory,True)
            app.tasks['search']={'status':'running'}
            http=create_server(app);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            try:
                c=HTTPConnection('127.0.0.1',http.server_port,timeout=3)
                c.request('POST','/api/close','{}',{'Content-Type':'application/json','X-WinPilot-Token':app.token})
                response=c.getresponse();self.assertEqual(response.status,200);self.assertTrue(json.loads(response.read())['ok']);c.close()
                thread.join(timeout=3);self.assertFalse(thread.is_alive())
            finally:http.shutdown();http.server_close()
    def test_conditional_state_has_no_repeated_payload(self):
        c=HTTPConnection('127.0.0.1',self.port,timeout=5)
        c.request('GET','/api/state',headers={'X-WinPilot-Token':self.app.token});r=c.getresponse();tag=r.getheader('ETag');r.read();c.close()
        self.assertTrue(tag)
        status,raw=self.req('/api/state',**{'If-None-Match':tag})
        self.assertEqual(status,304);self.assertEqual(raw,b'')
    def test_conditional_state_still_requires_auth(self):
        self.assertEqual(self.req('/api/state',auth=False,**{'If-None-Match':'"anything"'})[0],403)
    def test_dns_rebinding(self): self.assertEqual(self.req('/api/state',Host='attacker.example')[0],403)
    def test_cross_origin(self): self.assertEqual(self.req('/api/preview',{},Origin='https://example.com')[0],403)
    def test_mutation_auth(self): self.assertEqual(self.req('/api/apply',{'apps':['Mozilla.Firefox']},auth=False)[0],403)
    def test_traversal(self): self.assertEqual(self.req('/../main.py')[0],404)
    def test_shell_route_absent(self): self.assertEqual(self.req('/api/run',{'command':'calc.exe'})[0],400)
    def test_open_allowlist(self): self.assertEqual(self.req('/api/open',{'id':'file:///etc/passwd'})[0],400)
    def test_demo_open_no_os(self):
        with patch('os.startfile',create=True,side_effect=AssertionError('must not open')):
            self.assertEqual(self.req('/api/open',{'id':'sound'})[0],200)
    def test_preview_no_changes(self):
        status,raw=self.req('/api/preview',{'settings':{'theme':'dark'}})
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['operations'][0]['kind'],'setting');self.assertFalse(self.app.engine.snapshot()['running'])
    def test_scan_blocks_apply(self):
        self.app.tasks['test']={'status':'running'}
        try:self.assertEqual(self.req('/api/apply',{'apps':['Mozilla.Firefox']})[0],400)
        finally:self.app.tasks.pop('test')


class AudioPlanTests(unittest.TestCase):
    def check(self,a):return validate_plan({'audio':a},copy.deepcopy(INFO),[],demo=True)
    def test_valid_audio(self):self.check([{'id':'demo-output','volume':50,'mute':False}])
    def test_volume_out_of_range(self):
        with self.assertRaises(ValueError):self.check([{'id':'demo-output','volume':101}])
    def test_boolean_is_not_volume(self):
        with self.assertRaises(ValueError):self.check([{'id':'demo-output','volume':True}])
    def test_disconnected_audio(self):
        with self.assertRaises(ValueError):self.check([{'id':'unplugged','volume':40}])
    def test_duplicate_endpoint(self):
        with self.assertRaises(ValueError):self.check([{'id':'demo-output','volume':40}]*2)
    def test_mute_type(self):
        with self.assertRaises(ValueError):self.check([{'id':'demo-output','mute':'false'}])
    def test_empty_audio_operation(self):
        with self.assertRaises(ValueError):self.check([{'id':'demo-output'}])

class InstallAndUndoTests(unittest.TestCase):
    def test_existing_app_is_not_reinstalled(self):
        backend=Windows()
        with patch.object(backend.package_manager,'ready',return_value={'ready':True}),patch.object(backend.package_manager,'resolve',return_value='winget.exe'),patch.object(backend,'run',return_value='Firefox Mozilla.Firefox') as run:
            message=backend.install_app('Mozilla.Firefox')
        self.assertIn('Уже установлена',message['message'])
        self.assertEqual(run.call_count,1)
    def test_installer_failure_not_success(self):
        from winpilot.packages import ProcessError,PackageError
        backend=Windows()
        with patch.object(backend.package_manager,'ready',return_value={'ready':True}),patch.object(backend.package_manager,'resolve',return_value='winget.exe'),patch.object(backend,'run',side_effect=[ProcessError(0x8a150014,'not installed'),ProcessError(0x8a150008,'download failed')]):
            with self.assertRaises(PackageError):backend.install_app('Mozilla.Firefox')
    def test_undo_retained_across_apply_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=Demo();engine=Engine(backend,directory,False);current=['dark']
            def wait():
                end=time.monotonic()+3
                while engine.snapshot()['running'] and time.monotonic()<end:time.sleep(.005)
                self.assertFalse(engine.snapshot()['running'])
            with patch.object(backend,'reg_snapshot',create=True,side_effect=lambda key:current.copy()),patch.object(backend,'apply_setting',create=True,side_effect=lambda key,value,adapter=None:current.__setitem__(0,value)),patch.object(backend,'restore_registry',create=True,side_effect=lambda values:current.__setitem__(0,values[0])):
                engine.start({'settings':{'theme':'light'}},INFO,[]);wait()
                engine.start({'settings':{'theme':'dark'}},INFO,[]);wait()
                self.assertEqual(len(engine.undo),2)
                engine.start_undo();wait()
                self.assertEqual(current[0],'light');self.assertTrue(engine.snapshot()['can_undo'])
                engine.start_undo();wait()
                self.assertEqual(current[0],'dark');self.assertFalse(engine.snapshot()['can_undo'])

if __name__=='__main__': unittest.main()
