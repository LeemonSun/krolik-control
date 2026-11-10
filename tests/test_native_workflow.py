import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from winpilot.demo import Demo, INFO
from winpilot.server import Application
from winpilot.engine import validate_plan
from winpilot.hardware import ordered_devices
from winpilot.native import set_input
from winpilot.recovery import checked_undo

class NativeWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=Application(Demo(),Path(__file__).parents[1]/'ui',self.tmp.name,True)
        self.app.info=copy.deepcopy(INFO)
    def tearDown(self):self.tmp.cleanup()
    def wait(self,name):
        deadline=time.monotonic()+3
        while self.app.tasks.get(name,{}).get('status')=='running' and time.monotonic()<deadline:time.sleep(.005)
        self.assertNotEqual(self.app.tasks[name]['status'],'running')
    def test_catalog_has_working_controls_and_no_windows_shortcuts(self):
        rows=self.app.catalog()
        self.assertNotIn('windows',{r['kind'] for r in rows})
        self.assertIn('page:monitor',{r['id'] for r in rows})
        self.assertIn('setting:mouse_swap',{r['id'] for r in rows})
    def test_fast_inventory_available_before_slow_metadata(self):
        gate=threading.Event()
        class Phased(Demo):
            def quick_inventory(self):return {**copy.deepcopy(INFO),'pending_groups':['power','network','language']}
            def inventory_details(self):
                gate.wait(3)
                return {'network':[], 'settings':{'layouts':'ru'},'pending_groups':[]}
        self.app.backend=Phased()
        self.app.scan_inventory();self.wait('inventory')
        try:
            self.assertEqual(self.app.tasks['inventory_details']['status'],'running')
            self.assertEqual(self.app.info['displays'][0]['current'],'2560x1440@144')
            self.assertFalse(self.app.blocking_scan())
            preview=self.app.post('/api/preview',{'displays':[{'id':'demo-display-1','mode':'2560x1440@180','orientation':0}]})
            self.assertEqual(preview['operations'][0]['kind'],'display')
            with self.assertRaises(ValueError):self.app.post('/api/preview',{'settings':{'sleep_ac':'10'}})
            # A slow metadata merge must not replace fast, newer display/input state.
            self.app.info['displays'][0]['current']='2560x1440@180'
            self.app.info['settings']['mouse_speed']='17'
        finally:gate.set();self.wait('inventory_details')
        self.assertEqual(self.app.info['displays'][0]['current'],'2560x1440@180')
        self.assertEqual(self.app.info['settings']['mouse_speed'],'17')
        self.assertEqual(self.app.info['settings']['layouts'],'ru')
    def test_metadata_failure_keeps_fast_inventory(self):
        class Broken(Demo):
            def quick_inventory(self):return {**copy.deepcopy(INFO),'pending_groups':['power']}
            def inventory_details(self):raise RuntimeError('WMI unavailable')
        self.app.backend=Broken();self.app.scan_inventory();self.wait('inventory')
        self.wait('inventory_details')
        self.assertEqual(self.app.tasks['inventory_details']['status'],'error')
        self.assertTrue(self.app.info['displays'])
        self.assertFalse(next(s for s in self.app.settings() if s['key']=='sleep_ac')['enabled'])
    def test_match_only_exact_hardware_and_compatible_ids(self):
        self.app.data={'drivers':[{'id':'GPU','hardware_ids':['PCI\\VEN_1002&DEV_73FF'],'compatible_ids':['PCI\\CC_0300']},{'id':'OTHER','hardware_ids':['PCI\\VEN_1002&DEV_73FE'],'compatible_ids':[]}],
          'driver_updates':[{'id':'match','driver':True,'hardware_id':'pci\\ven_1002&dev_73ff'}, {'id':'compatible','driver':True,'hardware_id':'PCI\\CC_0300'},{'id':'partial','driver':True,'hardware_id':'PCI\\VEN_1002'},{'id':'missing','driver':True}]}
        rows={u['id']:u['device_ids'] for u in self.app.updates()}
        self.assertEqual(rows,{'match':['GPU'],'compatible':['GPU'],'partial':[],'missing':[]})
        self.assertEqual(self.app.state()['data']['driver_updates'][0]['device_ids'],['GPU'])
    def test_priorities_not_alphabetical_driver_dump(self):
        devices=[{'id':str(i),'name':name,'category':category,'problem':0} for i,(name,category) in enumerate([('AAA Software','SoftwareDevice'),('USB hub','USB'),('Realtek Audio','MEDIA'),('NVIDIA RTX','Display'),('Intel Processor','Processor'),('AMD SMBus','System'),('Ethernet','Net')])]
        self.assertEqual([d['name'] for d in ordered_devices(devices)],['NVIDIA RTX','Intel Processor','AMD SMBus','Ethernet','Realtek Audio','USB hub','AAA Software'])
    def test_problem_devices_not_buried(self):
        devices=[{'id':'hidden','name':'Unknown','category':'Unknown','problem':28}]+[{'id':str(i),'name':str(i),'category':'System','problem':0} for i in range(200)]
        self.assertEqual(ordered_devices(devices)[0]['id'],'hidden')
    def test_updated_device_inventory_preserves_dns_and_input(self):
        old=copy.deepcopy(self.app.info['settings'])
        self.app.task('devices',lambda:{'displays':[],'endpoints':[]});self.wait('devices')
        self.assertEqual(self.app.info['settings'],old)
        self.assertEqual(self.app.info['displays'],[])
    def test_new_native_settings_snapshot_is_recoverable(self):
        entries=[{'kind':'setting','key':k,'value':v} for k,v in [('double_click','487'),('mouse_swap','1'),('cursor_shadow','0'),('mouse_sonar','1'),('mouse_vanish','1'),('wheel_horizontal','4294967295')]]
        self.assertEqual(checked_undo(entries),entries)
        with self.assertRaises(ValueError):checked_undo([{'kind':'setting','key':'double_click','value':'99999'}])
    def test_spi_boolean_pointer_argument_and_ui_argument(self):
        from unittest.mock import MagicMock
        u=MagicMock();u.SystemParametersInfoW.return_value=1
        with patch('winpilot.native.user32',return_value=u):
            set_input('mouse_swap','1')
            self.assertEqual(u.SystemParametersInfoW.call_args.args,(0x21,1,None,3))
            set_input('mouse_sonar','1')
            self.assertEqual(u.SystemParametersInfoW.call_args.args[0],0x101D)
            self.assertEqual(u.SystemParametersInfoW.call_args.args[1],0)
            self.assertEqual(u.SystemParametersInfoW.call_args.args[2].value,1)
    def test_new_programs_include_automatic_setup(self):
        from winpilot.catalog import APPS
        self.assertIn('Opera.Opera',APPS);self.assertIn('Yandex.Browser',APPS);self.assertIn('EpicGames.EpicGamesLauncher',APPS)
        for ident in APPS:validate_plan({'apps':[ident]},self.app.info,[],demo=True)
        self.app.info['winget']=False
        response=self.app.post('/api/preview',{'apps':['Opera.Opera']})
        self.assertEqual([r['kind'] for r in response['operations']],['package_manager','app'])

if __name__=='__main__':unittest.main()
