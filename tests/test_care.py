import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from winpilot.care import audio_findings,network_findings,performance_findings,CareCenter
from winpilot.benchmarks import interpret
from winpilot.audio_tools import voice_metrics,pcm_values
from winpilot.server import Application
from winpilot.demo import Demo
from winpilot.workspace import ui_preferences

def wait(c):
    deadline=time.monotonic()+4
    while c.state['running'] and time.monotonic()<deadline:time.sleep(.01)
    assert not c.state['running']

class Findings(unittest.TestCase):
    def test_muted_device_action(self):
        r=audio_findings({'endpoints':[{'id':'a','name':'Speaker','flow':0,'volume':0,'controllable':True,'mute':True}]});self.assertEqual(next(f for f in r if f['action'])['action'],'audio_level')
    def test_missing_device_no_blind_repair(self):self.assertTrue(all(f['action'] is None for f in audio_findings({})))
    def test_stopped_and_running_services(self):
        for status,wanted in [('Stopped',True),('Running',False)]:self.assertEqual(any(f['action']=='audio_service' for f in audio_findings({'services':[{'name':'Audiosrv','status':status}]})),wanted)
    def test_session_separate(self):self.assertTrue(any(f['action']=='session_unmute' for f in audio_findings({'sessions':[{'id':'s','name':'Game','mute':True,'volume':60}]})))
    def test_static_ip_never_renewed(self):
        for dhcp,expected in [(False,False),(True,True)]:self.assertEqual(any(f['action']=='dhcp_renew' for f in network_findings({'adapters':[{'name':'LAN','guid':'g','up':True,'dhcp':dhcp,'ipv4':['169.254.1.1']}]})),expected)
    def test_unknown_dns_not_failure(self):self.assertFalse(any(f['action']=='dns_flush' for f in network_findings({})))
    def test_dns_failure_qualified(self):self.assertIn('не доказанная',next(f for f in network_findings({'dns':False}) if f['action']=='dns_flush')['detail'])
    def test_icmp_loss_not_proof(self):self.assertTrue(any('не доказательство' in f['detail'] for f in network_findings({'pings':[{'label':'router','sent':5,'received':2}]})))
    def test_short_observation_not_diagnosis(self):self.assertEqual(performance_findings([{'gpu':100}])[0]['id'],'few_samples')
    def test_single_spike_not_bottleneck(self):self.assertFalse(any(f['id']=='gpu_busy' for f in performance_findings([{'gpu':100}]+[{'gpu':10}]*7)))
    def test_sustained_load(self):self.assertEqual(len([f for f in performance_findings([{'gpu':99,'cpu_core':99,'ram_percent':95,'disk_ms':80}]*8) if f['level']=='warning']),4)
    def test_missing_counters_not_zero(self):self.assertTrue(any(f['id']=='missing_counters' for f in performance_findings([{'ram_percent':10}]*8)))
    def test_zero_benchmark_unavailable(self):
        m={'gpu_ms':0};interpret(m);self.assertIsNone(m['gpu_ms'])
    def test_benchmark_comparison(self):self.assertEqual(len([f for f in interpret({'cpu_single_mloops':40,'gpu_ms':4},{'cpu_single_mloops':100,'gpu_ms':2}) if f['id'].startswith('regression_')]),2)

class Voice(unittest.TestCase):
    def test_silence_and_clipping(self):
        for sample,expected in [(0,-120),(32767,0)]:self.assertAlmostEqual(voice_metrics({'data':struct.pack('<h',sample)*600,'format':{'subtype':1,'bits':16,'rate':100,'channels':1}})['peak_dbfs'],expected,delta=.1)
    def test_nonfinite_float(self):self.assertEqual(pcm_values(struct.pack('<fff',float('nan'),float('inf'),.5),{'subtype':3,'bits':32}),[0,0,.5])
    def test_24bit_signed(self):self.assertEqual(pcm_values(b'\x00\x00\x80',{'subtype':1,'bits':24}),[-1])
    def test_empty_recording(self):
        with self.assertRaises(ValueError):voice_metrics({'data':b'','format':{'rate':100,'channels':1,'subtype':1,'bits':16}})

class Jobs(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.app=Application(Demo(),Path(__file__).parents[1]/'ui',self.tmp.name,True);self.app.info=self.app.backend.inventory();self.c=self.app.care
    def tearDown(self):wait(self.c);self.tmp.cleanup()
    def test_idle_on_creation(self):self.assertFalse(self.c.state['running']);self.assertEqual(self.c.state['reports'],[])
    def test_confirmation_required(self):
        with self.assertRaises(ValueError):self.c.start('speed')
    def test_unknown_kind(self):
        with self.assertRaises(ValueError):self.c.start('arbitrary')
    def test_known_microphone_required(self):
        with self.assertRaises(ValueError):self.c.start('voice',{'confirmed':True,'id':'unknown'})
    def test_all_demo_jobs(self):
        for kind in ['audio','network','system','speed','observe','benchmark','integrity','repair_system','driver_backup','driver_restore','voice']:
            self.c.start(kind,{'confirmed':True,'id':'demo-microphone','backup':'Drivers-Demo'});wait(self.c);self.assertFalse(self.c.state.get('error'),kind);self.assertTrue(self.c.state['reports'][0]['demo'])
        self.assertEqual(len(self.c.state['reports']),8);self.assertEqual(len(list(self.c.directory.glob('report-*.json'))),8)
    def test_persist_without_reexecution(self):
        self.c.start('audio');wait(self.c);other=CareCenter(self.app);self.assertEqual(other.state['reports'][0]['kind'],'audio');self.assertFalse(other.state['running'])
    def test_token_single_use(self):
        self.c.start('network');wait(self.c);r=self.c.state['reports'][0];f=next(f for f in r['findings'] if f['action']=='dns_flush');p=self.c.preview(r['id'],f['id']);self.c.fix(p['token']);wait(self.c)
        with self.assertRaises(ValueError):self.c.fix(p['token'])
    def test_stale_finding(self):
        self.c.start('network');wait(self.c);r=self.c.state['reports'][0];r['time']-=1000
        with self.assertRaises(ValueError):self.c.preview(r['id'],r['findings'][0]['id'])
    def test_excludes_mutations(self):
        self.c.state['running']=True
        try:
            with self.assertRaises(ValueError):self.app.post('/api/scan',{})
            with self.assertRaises(ValueError):self.app.post('/api/apply',{'settings':{'extensions':'on'}})
        finally:self.c.state['running']=False
    def test_no_parallel_job(self):
        self.c.state['running']=True
        try:
            with self.assertRaises(ValueError):self.c.start('audio')
        finally:self.c.state['running']=False
    def test_no_termination_of_repair(self):
        self.c.state.update(running=True,kind='repair_system')
        try:self.assertFalse(self.c.stop());self.assertFalse(self.c.cancel.is_set())
        finally:self.c.state['running']=False
    def test_care_page_persistence(self):self.assertEqual(ui_preferences({'last_page':'care'})['last_page'],'care')
    def test_injected_service_rejected(self):
        from winpilot.care_windows import repair
        with self.assertRaises(ValueError):repair(self.c,{'action':'audio_service','target':'Audiosrv; Remove-Item C:\\'})


class CareRegression(unittest.TestCase):
    def test_partial_audio_never_claims_everything_ok(self):
        rows=audio_findings({'endpoints':[{'id':'o','name':'Speaker','flow':0,'volume':40},{'id':'i','name':'Mic','flow':1,'volume':70}],'probe_error':'WMI failed'});self.assertFalse(any(r['id']=='audio_ok' for r in rows))
    def test_unknown_adapters_not_disconnected(self):self.assertFalse(any(r['id']=='no_link' for r in network_findings({'adapters_unknown':True})))
    def test_policy_denial_not_offered_global_allow(self):self.assertFalse(any(r['action']=='mic_access' for r in audio_findings({'microphone_access':'Deny','microphone_policy':2})))
    def test_only_left_channel(self):
        from winpilot.audio_tools import tone_samples
        values=struct.unpack('<'+'h'*400,tone_samples(200,2,48000,16,1,0));self.assertTrue(any(values[::2]));self.assertFalse(any(values[1::2]))
    def test_missing_right_channel_rejected(self):
        from winpilot.audio_tools import tone_samples
        with self.assertRaises(ValueError):tone_samples(200,1,48000,16,1,1)
    def test_cancelled_job_does_not_save_complete_report(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            app=Application(Demo(),Path(__file__).parents[1]/'ui',directory,True);app.info=app.backend.inventory()
            def delayed(c,k,b):
                c.cancel.wait(1);c.stage('After cancel');return {'findings':[]}
            with patch('winpilot.care_windows.demo_run',side_effect=delayed):app.care.start('observe');app.care.stop();wait(app.care)
            self.assertEqual(app.care.state['reports'],[]);self.assertIn('Остановлено',app.care.state['error'])
    def test_undo_from_wrong_report_cannot_change_setting(self):
        from winpilot.workspace import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            app=Application(Demo(),Path(__file__).parents[1]/'ui',directory,True);atomic_json(app.care.directory/'last-repair-undo.json',{'kind':'mic_access','previous':'Deny','report':'new'})
            with self.assertRaises(ValueError):app.care.undo_last('old')
            self.assertTrue((app.care.directory/'last-repair-undo.json').exists())
    def test_failed_snapshot_prevents_permission_change(self):
        from unittest.mock import patch
        from winpilot.care_windows import repair
        with tempfile.TemporaryDirectory() as directory:
            app=Application(Demo(),Path(__file__).parents[1]/'ui',directory,True);app.care.active_repair='r'
            with patch('winpilot.care_windows.audio_probe',return_value={'microphone_access':'Deny'}),patch('winpilot.workspace.atomic_json',side_effect=OSError('disk full')),patch('winpilot.care_windows.psjson') as change:
                with self.assertRaises(OSError):repair(app.care,{'action':'mic_access'})
                change.assert_not_called()


class SpeedMeasurement(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.cancel=__import__('threading').Event();self.c=SimpleNamespace(cancel=self.cancel,stage=lambda text:None)
    def factory(self,truncate=False,bad_status=False):
        owner=self
        class Connection:
            def __init__(self,*a,**k):self.closed=False;self.path='';self.remaining=0
            def connect(self):pass
            def close(self):self.closed=True
            def request(self,method,path,body=None,headers=None):
                self.path=path;self.remaining=int(path.split('bytes=')[1].split('&')[0]) if 'bytes=' in path else 0
                if truncate and self.remaining:self.remaining-=1
            def getresponse(self):return self
            @property
            def status(self):return 503 if bad_status else 200
            def read(self,size):
                count=min(size,self.remaining);self.remaining-=count;return b'x'*count
        return Connection
    def test_complete_payload_has_real_metrics_and_unknown_loaded_latency(self):
        from winpilot.care_windows import speed_test
        result=speed_test(self.c,self.factory());self.assertGreater(result['metrics']['download_mbps'],0);self.assertEqual(result['metrics']['transferred_mb'],28);self.assertIsNone(result['metrics']['loaded_latency_ms'])
    def test_truncated_download_not_a_speed_result(self):
        from winpilot.care_windows import speed_test
        with self.assertRaises(ValueError):speed_test(self.c,self.factory(truncate=True))
    def test_server_error_not_zero_speed(self):
        from winpilot.care_windows import speed_test
        with self.assertRaises(OSError):speed_test(self.c,self.factory(bad_status=True))

if __name__=='__main__':unittest.main()
