import copy
import json
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from winpilot.pc import PcCenter,FastCounters,temperatures,number
from winpilot.server import Application,create_server
from winpilot.demo import Demo

def app(demo=True,backend=None):
    return SimpleNamespace(demo=demo,backend=backend or SimpleNamespace(),lock=threading.RLock(),info={},data_revision=0,engine=SimpleNamespace(snapshot=lambda:{'running':False}),care=SimpleNamespace(state={'running':False}))

def until(fn,timeout=4):
    deadline=time.monotonic()+timeout
    while not fn():
        if time.monotonic()>deadline:raise AssertionError('Timed out')
        time.sleep(.02)

class PcTests(unittest.TestCase):
    def test_closed_monitor_cannot_launch_a_provider(self):
        p=PcCenter(app(False));p.close()
        with patch.dict('os.environ',{'SystemRoot':'C:\\Windows'}),patch('winpilot.pc.subprocess.Popen') as launch:
            with self.assertRaises(OSError):p._start_provider(__import__('queue').Queue())
            launch.assert_not_called()

    def test_close_during_provider_launch_does_not_orphan_process(self):
        p=PcCenter(app(False));entered=threading.Event();release=threading.Event()
        process=SimpleNamespace(stdout=io.BytesIO(),poll=lambda:None,kill=lambda:None)
        from unittest.mock import Mock
        process.kill=Mock()
        def launch(*args,**kwargs):entered.set();release.wait(2);return process
        with patch.dict('os.environ',{'SystemRoot':'C:\\Windows'}),patch('winpilot.pc.subprocess.Popen',side_effect=launch):
            worker=threading.Thread(target=lambda:p._start_provider(__import__('queue').Queue()));worker.start();self.assertTrue(entered.wait(1))
            close=threading.Thread(target=p.close);close.start();release.set();worker.join(2);close.join(2)
            process.kill.assert_called_once()

    def test_rejects_nonfinite_and_boolean_measurements(self):
        for value in (None,True,'40',float('nan'),float('inf'),-1,101):self.assertIsNone(number(value))
        self.assertEqual(number(0),0);self.assertEqual(number(100),100)

    def test_temperature_mapping_excludes_disk_acpi_and_invalid(self):
        raw={'source':'root/LibreHardwareMonitor','hardware':[{'id':'/amdcpu/0','type':'Cpu','name':'Ryzen'},{'id':'/gpu/0','type':'GpuAmd','name':'Radeon'}], 'sensors':[{'parent':'/amdcpu/0','name':'Tctl','value':61.5},{'parent':'/gpu/0','name':'GPU Core','value':52},{'parent':'/hdd/0','value':33},{'parent':'/acpi/0','value':28},{'parent':'/amdcpu/0','value':float('nan')},{'parent':'/amdcpu/0','value':True}]}
        rows=temperatures(raw);self.assertEqual([(x['kind'],x['celsius']) for x in rows],[('cpu',61.5),('gpu',52)])
        self.assertEqual(rows[1]['hardware'],'Radeon')
        self.assertEqual(temperatures({'sensors':None,'hardware':None}),[])

    def test_monitor_starts_lazily_and_has_single_worker(self):
        p=PcCenter(app())
        try:
            self.assertIsNone(p.worker);self.assertEqual(p.value['hardware_status'],'idle')
            p.read();first=p.worker
            for _ in range(5):p.read()
            self.assertIs(first,p.worker)
            until(lambda:p.value['live'] is not None and p.value['hardware_status']=='done')
            value=p.read();self.assertTrue(value['demo']);self.assertEqual(len(value['hardware']['memory']),2)
            value['hardware']['memory'].clear();self.assertEqual(len(p.value['hardware']['memory']),2)
            self.assertIn('cpu_temperature',p.value['history'][0])
        finally:p.close();p.worker.join(timeout=3)

    def test_inactive_page_stops_sampling(self):
        p=PcCenter(app())
        try:
            p.read();until(lambda:p.value['monitoring'])
            p.last_seen=time.monotonic()-10;p.worker.join(timeout=3)
            self.assertFalse(p.worker.is_alive());self.assertFalse(p.value['monitoring'])
        finally:p.close()

    def test_running_job_does_not_start_sampler_or_probe(self):
        a=app();a.engine.snapshot=lambda:{'running':True};p=PcCenter(a)
        self.assertTrue(p.read()['paused']);self.assertIsNone(p.worker);self.assertEqual(p.value['hardware_status'],'idle');p.close()

    def test_failed_refresh_preserves_last_hardware(self):
        backend=SimpleNamespace(psjson=lambda *a,**k:(_ for _ in ()).throw(OSError('provider failed')))
        p=PcCenter(app(False,backend));p.value['hardware']={'gpu':[{'name':'Previous GPU'}]}
        try:
            p.read();until(lambda:p.value['hardware_status']=='error')
            self.assertEqual(p.read()['hardware']['gpu'][0]['name'],'Previous GPU')
        finally:
            p.close()
            if p.worker:p.worker.join(timeout=3)

    def test_native_counter_delta_and_memory_units(self):
        class Kernel:
            samples=iter([(100,200,100),(150,300,200),(160,300,200)])
            def GetSystemTimes(self,idle,kernel,user):
                values=next(self.samples)
                for ptr,val in zip((idle,kernel,user),values):ptr._obj.value=val
                return 1
            def GlobalMemoryStatusEx(self,ptr):ptr._obj.total=32*1024**3;ptr._obj.avail=12*1024**3;return 1
        counter=FastCounters()
        with patch('winpilot.pc.os.name','nt'),patch('winpilot.pc.ctypes.WinDLL',return_value=Kernel(),create=True):
            self.assertIsNone(counter.read()['cpu']);row=counter.read();self.assertEqual(row['cpu'],75);self.assertEqual(row['ram_percent'],62.5);self.assertEqual(row['ram_used_gb'],20);self.assertIsNone(counter.read()['cpu'])

    def test_inspection_only_allows_readonly_known_checks(self):
        calls=[]
        a=app(False,SimpleNamespace(run=lambda argv,timeout:calls.append(argv) or 'example'))
        p=PcCenter(a);result=p.inspect('sleep')
        self.assertEqual([x[1] for x in calls],['/lastwake','/requests','/waketimers']);self.assertEqual(len(result['checks']),3)
        with self.assertRaises(ValueError):p.inspect('repair')
        p.close()

    def test_pc_api_requires_token_and_registers_new_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(__file__).parents[1];a=Application(Demo(),root/'ui',directory,True);http=create_server(a);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{http.server_port}'
            try:
                with self.assertRaises(HTTPError) as error:urlopen(base+'/api/pc')
                self.assertEqual(error.exception.code,403);self.assertIsNone(a.pc.worker)
                request=Request(base+'/api/pc',headers={'X-WinPilot-Token':a.token})
                with urlopen(request) as response:self.assertTrue(json.load(response)['demo'])
                for file in ('pc.js','pc.css'):
                    with urlopen(base+'/'+file) as response:self.assertEqual(response.status,200)
            finally:a.pc.close();http.shutdown();http.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
