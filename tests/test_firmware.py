import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from winpilot.firmware import FirmwareCenter,normalize,setting_type,fingerprint,WRITE_PS
from winpilot.server import Application,create_server
from winpilot.demo import Demo

def raw():
    return {'bios':[{'vendor':'OEM','version':'1.0'}],'board':[{'vendor':'Dell','model':'Board'}],'system':[{'vendor':'Dell','model':'PC'}],'boot':'boot1','encryption':False,'memory':[{'slot':'A2','part':'Kit','bytes':16*1024**3,'configured':4800,'type':34}], 'oem':{'provider':'dell','writer':True,'password':False,'rows':[{'name':'XMP Profile','current':'Disabled','choices':['Disabled','Profile 1'],'readonly':False,'physical':False}]}}

class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.raw=raw();self.backend=SimpleNamespace(is_admin=lambda:True,display_guard=SimpleNamespace(status=lambda:None),psjson=Mock(return_value={'accepted':True,'code':'0','stage':'set'}),run=Mock())
        self.app=SimpleNamespace(demo=False,backend=self.backend,engine=SimpleNamespace(snapshot=lambda:{'running':False}),care=SimpleNamespace(state={'running':False}),tasks={},data={})
        self.fw=FirmwareCenter(self.app,self.temp.name);self.fw._read=lambda:normalize(copy.deepcopy(self.raw),'uefi');self.scan()
    def scan(self):self.app.data['firmware']=self.fw.scan();return self.app.data['firmware']
    def preview(self,**extra):return self.fw.preview({'action':'setting','name':'XMP Profile','value':'Profile 1',**extra})
    def intent(self):
        p=self.preview();return self.fw.consume({'token':p['token'],'confirmed':True,'memory_ack':True})
    def test_allowlist_excludes_boot_password_voltage_and_substring_matches(self):
        for name in ('SecureBoot','SataMode','BootOrder','MemoryVoltage','XMP Voltage','Clear TPM','NotXMP','MemoryProfilePassword'):
            self.assertIsNone(setting_type(name))
        self.assertEqual(setting_type('EXPO Profile')[0],'memory')
    def test_unknown_metadata_password_and_readonly_fail_closed(self):
        for field,value in [('password',None),('password',True),('writer',False)]:
            r=raw();r['oem'][field]=value;self.assertFalse(normalize(r,'uefi')['settings'][0]['writable'])
        for field,value in [('readonly',None),('readonly',True),('physical',None),('physical',True)]:
            r=raw();r['oem']['rows'][0][field]=value;self.assertFalse(normalize(r,'uefi')['settings'][0]['writable'])
    def test_duplicate_oem_attribute_cannot_be_written(self):
        r=raw();r['oem']['rows'].append(copy.deepcopy(r['oem']['rows'][0]));self.assertFalse(normalize(r,'uefi')['settings'][0]['writable'])
    def test_choices_preserve_case_reject_injection_and_unknown_current(self):
        r=raw();r['oem']['rows'][0]['choices']+=['profile 1','x,y','x;reset','bad\x00value']
        s=normalize(r,'uefi')['settings'][0];self.assertEqual(s['choices'],['Disabled','Profile 1','profile 1'])
        r['oem']['rows'][0]['current']='not-listed';self.assertFalse(normalize(r,'uefi')['settings'][0]['writable'])
    def test_unknown_measurements_never_fabricated(self):
        r=raw();r['memory'][0].update(configured=0,voltage=float('nan'),bytes=True);d=normalize(r,None)
        self.assertIsNone(d['memory'][0]['configured']);self.assertIsNone(d['memory'][0]['voltage']);self.assertIsNone(d['memory'][0]['bytes']);self.assertIsNone(d['secure_boot'])
    def test_snapshot_saves_no_keys_passwords_or_serials(self):
        self.raw['recovery_password']='secret';self.raw['memory'][0]['serial']='secret';self.raw['oem']['password_value']='secret'
        data=self.fw.baseline();self.assertEqual(data['saved']['baseline']['memory'][0]['configured'],4800)
        self.assertNotIn('secret',self.fw.path.read_text())
    def test_token_is_one_use_and_requires_risk_ack(self):
        p=self.preview()
        with self.assertRaises(ValueError):self.fw.consume({'token':p['token'],'confirmed':True})
        i=self.fw.consume({'token':p['token'],'confirmed':True,'memory_ack':True})
        self.assertEqual(i['before'],'Disabled')
        with self.assertRaises(ValueError):self.fw.consume({'token':p['token'],'confirmed':True,'memory_ack':True})
    def test_expired_preview_and_stale_scan_rejected(self):
        p=self.preview();self.fw.intent['expires']=time.monotonic()-1
        with self.assertRaises(ValueError):self.fw.consume({'token':p['token'],'confirmed':True,'memory_ack':True})
        self.app.data['firmware']['scanned_at']=time.time()-121
        with self.assertRaises(ValueError):self.preview()
    def test_encryption_unknown_or_active_requires_recovery_ack(self):
        for protection in (True,None):
            self.raw['encryption']=protection;self.scan();p=self.preview();self.assertTrue(p['recovery_required'])
            with self.assertRaises(ValueError):self.fw.consume({'token':p['token'],'confirmed':True,'memory_ack':True})
            self.fw.consume({'token':p['token'],'confirmed':True,'memory_ack':True,'recovery_saved':True})
    def test_any_job_display_guard_and_nonadmin_block_actions(self):
        self.app.tasks['x']={'status':'running'}
        with self.assertRaises(ValueError):self.preview()
        self.app.tasks.clear();self.backend.is_admin=lambda:False
        with self.assertRaises(ValueError):self.preview()
        self.backend.is_admin=lambda:True;self.backend.display_guard.status=lambda:{'id':'x'}
        with self.assertRaises(ValueError):self.preview()
    def test_hardware_and_capability_change_prevent_write(self):
        for mutate in (lambda:self.raw['memory'][0].update(part='Changed'),lambda:self.raw['oem'].update(password=True),lambda:self.raw.update(boot='boot2'),lambda:self.raw['bios'][0].update(version='2.0')):
            self.raw=raw();self.scan();i=self.intent();mutate()
            with self.assertRaises(ValueError):self.fw.execute(i)
        self.backend.psjson.assert_not_called()
    def test_journal_is_durable_before_oem_write(self):
        def write(*args,**kwargs):
            j=json.loads(self.fw.path.read_text())['change'];self.assertEqual(j['state'],'prepared');self.assertEqual(j['before'],'Disabled');return {'accepted':True}
        self.backend.psjson.side_effect=write;self.fw.execute(self.intent());self.assertEqual(self.fw.record['change']['state'],'accepted')
    def test_failed_disk_write_prevents_firmware_call(self):
        i=self.intent()
        with patch('winpilot.firmware.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.fw.execute(i)
        self.backend.psjson.assert_not_called()
    def test_exception_or_oem_rejection_is_uncertain_and_blocks_retry(self):
        self.backend.psjson.side_effect=TimeoutError();i=self.intent()
        with self.assertRaises(ValueError):self.fw.execute(i)
        self.assertEqual(self.fw.record['change']['state'],'uncertain');self.scan()
        with self.assertRaises(ValueError):self.preview()
        loaded=FirmwareCenter(self.app,self.temp.name);self.assertEqual(loaded.record['change']['state'],'uncertain')
    def test_acceptance_is_not_verification_before_reboot(self):
        self.fw.execute(self.intent());self.raw['oem']['rows'][0]['current']='Profile 1';self.scan()
        self.assertEqual(self.fw.record['change']['state'],'accepted')
        self.raw['boot']='boot2';self.scan();self.assertEqual(self.fw.record['change']['state'],'verified')
    def test_reboot_mismatch_and_missing_setting_not_success(self):
        self.fw.execute(self.intent());self.raw['boot']='boot2';self.scan();self.assertEqual(self.fw.record['change']['state'],'mismatch')
        self.fw.record['change']['state']='accepted';self.raw['oem']['rows']=[];self.scan();self.assertEqual(self.fw.record['change']['state'],'unavailable')
    def test_reboot_of_different_machine_cannot_verify(self):
        self.fw.execute(self.intent());self.raw['boot']='boot2';self.raw['board'][0]['model']='Other';self.scan();self.assertEqual(self.fw.record['change']['state'],'accepted')
    def test_reboot_command_is_exact_and_never_forces_apps_closed(self):
        p=self.fw.preview({'action':'restart','target':'uefi'});i=self.fw.consume({'token':p['token'],'confirmed':True})
        with patch.dict('os.environ',{'SystemRoot':'C:/Windows'}):self.fw.execute(i)
        args=self.backend.run.call_args.args[0];self.assertEqual(args[1:],['/r','/t','0','/fw']);self.assertNotIn('/f',args)
    def test_legacy_or_unknown_firmware_cannot_request_uefi(self):
        for mode in (None,'legacy'):
            self.app.data['firmware']['mode']=mode
            with self.assertRaises(ValueError):self.fw.preview({'action':'restart','target':'uefi'})
    def test_corrupt_journal_blocks_mutations(self):
        self.fw.path.write_text('{bad');f=FirmwareCenter(self.app,self.temp.name);f._read=self.fw._read
        with self.assertRaises(ValueError):f.preview({'action':'restart','target':'uefi'})
    def test_invalid_journal_shape_cannot_crash_the_page(self):
        for value in ({'version':1,'change':'broken'},{'version':1,'baseline':{'time':1,'boot':'x','machine':{},'bios':[],'memory':['broken']}}):
            self.fw.path.write_text(json.dumps(value));f=FirmwareCenter(self.app,self.temp.name);f._read=self.fw._read
            data=f.scan();self.assertTrue(data['warning']);self.assertEqual(data['saved'],{})
    def test_demo_never_calls_write_or_reboot(self):
        self.app.demo=True;self.fw.execute(self.intent());self.backend.psjson.assert_not_called()
        self.fw.intent=None;p=self.fw.preview({'action':'restart','target':'windows'});i=self.fw.consume({'token':p['token'],'confirmed':True});self.fw.execute(i);self.backend.run.assert_not_called()

class FirmwareApiTests(unittest.TestCase):
    def test_fast_repeated_task_publishes_new_data_even_with_same_task_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            a=Application(Demo(),Path(__file__).parents[1]/'ui',d,True)
            def finish(value):
                a.task('firmware',lambda:{'value':value})
                deadline=time.time()+2
                while a.tasks['firmware']['status']=='running' and time.time()<deadline:time.sleep(.001)
                self.assertEqual(a.tasks['firmware']['status'],'done')
                a.tasks['firmware']={'status':'done','seconds':0,'finished':123}
            finish(1);before=a.state_tag();finish(2)
            self.assertNotEqual(before,a.state_tag());self.assertEqual(a.data['firmware']['value'],2)

    def test_capability_auth_and_async_scan(self):
        with tempfile.TemporaryDirectory() as d:
            a=Application(Demo(),Path(__file__).parents[1]/'ui',d,True);a.scan_inventory();h=create_server(a);threading.Thread(target=h.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{h.server_port}'
            try:
                req=Request(base+'/api/firmware/scan',data=b'{}',headers={'Content-Type':'application/json'})
                with self.assertRaises(HTTPError) as e:urlopen(req)
                self.assertEqual(e.exception.code,403)
                req.add_header('X-WinPilot-Token',a.token);self.assertTrue(json.load(urlopen(req))['ok'])
                deadline=time.time()+3
                while a.tasks['firmware']['status']=='running' and time.time()<deadline:time.sleep(.01)
                self.assertEqual(a.tasks['firmware']['status'],'done');self.assertEqual(a.data['firmware']['mode'],'uefi')
                for asset in ('firmware.js','firmware.css'):self.assertEqual(urlopen(base+'/'+asset).status,200)
                self.assertTrue(any(r['id']=='page:firmware' for r in a.catalog()))
            finally:a.pc.close();h.shutdown();h.server_close()
