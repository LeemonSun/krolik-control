"""Product regressions and real temporary-file transactions, without hardware writes."""
import copy,ctypes as C,hashlib,json,os,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from winpilot import files
from winpilot.drive_health import parse
from winpilot.engine import Engine
from winpilot.demo import Demo
from winpilot.server import Application
from winpilot.installed_apps import local_inventory
from winpilot.pending import PendingChecks,fingerprint
from winpilot.power import PowerLease
from winpilot.software import SoftwareCenter,digest
from winpilot.toolbox import host_value
from winpilot.workspace import atomic_json

class ProductTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.stop=threading.Event();self.stage=lambda _:None
 def tearDown(self):self.tmp.cleanup()
 def app(self):
  a=Application(Demo(),Path(__file__).parents[1]/'ui',self.root/'state',True);a.info=a.backend.inventory();self.addCleanup(a.pc.close);self.addCleanup(a.toolbox.close);return a
 def wait(self,a):
  end=time.monotonic()+5
  while a.toolbox.state['running'] and time.monotonic()<end:time.sleep(.005)
  self.assertFalse(a.toolbox.state['running'])
 def test_versions_and_architectures_do_not_depend_on_registry_order(self):
  entries=[dict(name='Mozilla Firefox',version='140',architecture='x64',scope='machine'),dict(name='Mozilla Firefox',version='115',architecture='x86',scope='user')]
  a=local_inventory(entries);self.assertEqual(a,local_inventory(entries[::-1]));r=next(r for r in a if r['id']=='Mozilla.Firefox');self.assertEqual(len(r['installations']),2);self.assertTrue(r['multiple_installations']);self.assertIn('115',r['version']);self.assertIn('140',r['version'])
 def test_pending_survives_restart_and_does_not_replay(self):
  op=dict(kind='startup',key='a',value=False,title='Test');p=PendingChecks(self.root);p.add(op,'unverified','Readback unavailable');q=PendingChecks(self.root);self.assertTrue(q.contains(op));self.assertEqual(q.snapshot()[0]['operation']['value'],False);q.remove(fingerprint(op));self.assertFalse(PendingChecks(self.root).snapshot())
 def test_corrupt_pending_never_loads(self):
  for value in ({},[{'operation':{'kind':'arbitrary'}}]):
   atomic_json(self.root/'pending-checks.json',value);p=PendingChecks(self.root);self.assertEqual(p.snapshot(),[]);self.assertTrue(p.warning)
 def pending_engine(self):
  e=Engine(Demo(),self.root);e.logfile=self.root/'apply-123.jsonl';op=dict(kind='startup',key='a',value=False,title='Test',status='unverified',_journal='apply-123.jsonl',_index=0);e.state.update(items=[copy.deepcopy(op)],log=str(e.logfile));e.record(0,'unverified','Waiting');e.pending.add(op,'unverified','Waiting');return e,op
 def test_confirmed_readback_updates_original_history_and_false_value(self):
  e,op=self.pending_engine();self.assertEqual(e._history()[0]['pending'],1);e=Engine(Demo(),self.root);e.resolve_check(fingerprint(op),dict(status='confirmed',message='Read back'));h=e._history()[0];self.assertEqual(h['success'],1);self.assertEqual(h['pending'],0);self.assertEqual(h['items'][0]['verification'],'confirmed');self.assertFalse(e.pending.snapshot())
 def test_dismiss_is_not_a_green_success(self):
  e,op=self.pending_engine();e.resolve_check(fingerprint(op),dict(status='closed',message='Unconfirmed'));h=e._history()[0];self.assertEqual(h['success'],0);self.assertEqual(h['closed'],1);self.assertFalse(e.pending.snapshot())
 def test_retry_saving_preserves_identity_for_later_readback(self):
  e,op=self.pending_engine();e.retry_persistence();e.resolve_check(fingerprint(op),dict(status='confirmed',message='Read back'))
  h=e._history()[0];self.assertEqual(h['success'],1);self.assertEqual(h['pending'],0);self.assertEqual(h['items'][0]['value'],False)
 def test_installations_are_not_verified_as_an_automatic_undo(self):
  from winpilot.windows import Windows
  b=Windows()
  with patch.object(b.package_manager,'_command') as command:
   for kind in ('driver_safety','package_manager','app','upgrade'):
    r=b.verify_undo({'kind':kind,'key':'example','value':True});self.assertEqual(r['status'],'unverified');self.assertNotIn('not defined',r['message'])
  command.assert_not_called()
 def test_pending_cannot_append_outside_original_matching_log(self):
  e,op=self.pending_engine();other=self.root/'outside';other.write_text('original');op['_journal']='../outside';e.pending.add(op,'unverified','Waiting');e.resolve_check(fingerprint(op),dict(status='confirmed',message='Read'));self.assertEqual(other.read_text(),'original');self.assertEqual(e._history()[0]['success'],0)
 def test_audio_undo_available_after_reopening_without_task(self):
  a=self.app();base=copy.deepcopy(a.info['endpoints'][0]);base.update(id='prior',flow=0,default_roles=[]);a.info['endpoints'][0].update(flow=0,default_roles=[1]);after=a.info['endpoints'][0]['id'];a.info['endpoints'].append(base);atomic_json(a.audio_router.path,dict(state='confirmed',before='prior',after=after,flow=0,role=1));self.assertTrue(a.state()['data']['audio_default']['previous_available']);a.info['endpoints'][0]['default_roles']=[];self.assertFalse(a.state()['data']['audio_default']['previous_available'])
 def test_analyze_does_not_follow_links_or_double_count_hardlinks(self):
  (self.root/'a').mkdir();(self.root/'a/x.bin').write_bytes(b'x'*20);os.link(self.root/'a/x.bin',self.root/'hard.bin');os.symlink(self.root/'a',self.root/'loop');r=files.analyze(self.root,self.stop,self.stage);self.assertEqual(r['bytes'],20);self.assertEqual(r['files'],1);self.assertGreater(r['skipped'],0)
 def test_duplicates_use_content_not_only_name_or_size(self):
  for name,data in [('one',b'abcd'),('two',b'abcd'),('three',b'xxxx')]: (self.root/name).write_bytes(data)
  r=files.duplicates(self.root,self.stop,self.stage);self.assertEqual(len(r['groups']),1);self.assertEqual(set(r['groups'][0]['paths']),{'one','two'});self.assertTrue((self.root/'two').exists())
 def test_hash_and_cancellation(self):
  p=self.root/'file';p.write_bytes(b'krolik');self.assertEqual(files.hash_file(p,self.stop,self.stage),hashlib.sha256(b'krolik').hexdigest());self.stop.set()
  with self.assertRaises(files.Stopped):files.hash_file(p,self.stop,self.stage)
 def test_scan_bounds_empty_directories(self):
  for i in range(15):(self.root/str(i)).mkdir()
  r,m=files.walk(self.root,self.stop,self.stage,max_files=2);self.assertTrue(m['limited']);self.assertEqual(r,[])
 def test_hash_rejects_symlink(self):
  (self.root/'f').write_text('real');os.symlink(self.root/'f',self.root/'s')
  with self.assertRaises(ValueError):files.hash_file(self.root/'s',self.stop,self.stage)
 def test_windows_reserved_names(self):
  for name in ['CON','NUL.txt','LPT1.pdf','foo.','foo ','../file','a:b','x\x00y','COM9.png']:
   with self.subTest(name=name):self.assertFalse(files.valid_name(name))
  self.assertTrue(files.valid_name('Фото 1.jpg'))
 def test_rename_conflict_never_overwrites(self):
  (self.root/'old').write_text('first');(self.root/'new').write_text('second')
  with self.assertRaises(ValueError):files.rename_preview(self.root,'old','new')
  self.assertEqual((self.root/'new').read_text(),'second')
 def test_real_rename_and_inverse_transaction(self):
  (self.root/'old-1').write_text('one');(self.root/'old-2').write_text('two');job=files.rename_preview(self.root,'old','new');result=files.rename_apply(job,self.root/'journal.json');self.assertEqual(result['count'],2);self.assertEqual((self.root/'new-1').read_text(),'one');saved=json.loads((self.root/'journal.json').read_text());inv=dict(root=str(self.root),rows=[dict(before=r['after'],after=r['before'],identity=r['identity']) for r in saved['rows']]);files.rename_apply(inv,self.root/'undo.json');self.assertEqual((self.root/'old-2').read_text(),'two')
 def test_rename_changed_source_rejected_before_any_move(self):
  p=self.root/'old';p.write_text('one');job=files.rename_preview(self.root,'old','new');p.write_text('different')
  with self.assertRaises(ValueError):files.rename_apply(job,self.root/'journal.json')
  self.assertTrue(p.exists());self.assertFalse((self.root/'new').exists())
 def test_rename_destination_race_rolls_back_source(self):
  (self.root/'old').write_text('one');job=files.rename_preview(self.root,'old','new');(self.root/'new').write_text('outsider')
  with self.assertRaises(OSError):files.rename_apply(job,self.root/'journal.json')
  self.assertEqual((self.root/'old').read_text(),'one');self.assertEqual((self.root/'new').read_text(),'outsider');self.assertEqual(json.loads((self.root/'journal.json').read_text())['state'],'error')
 def test_rename_partial_failure_rolls_back_completed_moves(self):
  for n in ('a-old','b-old'):(self.root/n).write_text(n)
  job=files.rename_preview(self.root,'old','new');move=files.move_noreplace;calls=[]
  def failure(src,dst):
   calls.append(1)
   if len(calls)==4:raise OSError('Injected destination failure')
   return move(src,dst)
  with patch('winpilot.files.move_noreplace',side_effect=failure),self.assertRaises(OSError):files.rename_apply(job,self.root/'journal.json')
  self.assertEqual((self.root/'a-old').read_text(),'a-old');self.assertEqual((self.root/'b-old').read_text(),'b-old');self.assertFalse((self.root/'a-new').exists())
 def test_power_is_explicit_and_released(self):
  p=PowerLease();self.addCleanup(p.close)
  for minutes,display in [(True,False),(1,False),(15,'yes')]:
   with self.assertRaises(ValueError):p.start(minutes,display,True)
  p.start(15,True,True);self.assertTrue(p.state()['active']);self.assertTrue(p.state()['display']);p.close();self.assertFalse(p.state()['active'])
 def test_expired_timer_cannot_release_a_new_power_request(self):
  p=PowerLease();self.addCleanup(p.close)
  p.start(15,True,True);old=p.generation;p.start(30,False,True);current=p.generation
  p._expire(old);self.assertTrue(p.state()['active']);self.assertFalse(p.state()['display'])
  p._expire(current);self.assertFalse(p.state()['active'])
 def test_nvme_counter_width_and_temperature_sentinels(self):
  raw=bytearray(512);raw[1:3]=(310).to_bytes(2,'little');raw[160:176]=(2**100).to_bytes(16,'little');r=parse(raw);self.assertEqual(r['temperature_c'],36.9);self.assertEqual(r['media_errors'],str(2**100));raw[1:3]=b'\xff\xff';self.assertIsNone(parse(raw)['temperature_c'])
  with self.assertRaises(ValueError):parse(b'bad')
 def test_domains_are_validated_before_powershell(self):
  for name in ['https://example.com','a;whoami','a b','a\nfoo','-bad.com','x'*64+'.com']:
   with self.assertRaises(ValueError):host_value(name)
  self.assertEqual(host_value('1.1.1.1'),'1.1.1.1');self.assertEqual(host_value('::1'),'::1');self.assertEqual(host_value('пример.рф'),'xn--e1afmkfd.xn--p1ai')
 def test_software_requires_fresh_one_use_confirmation(self):
  a=self.app();a.software.scan();p=a.software.preview({'id':'demo-0','action':'remove'})
  with self.assertRaises(ValueError):a.software.consume({'token':p['token']})
  job=a.software.consume({'token':p['token'],'confirmed':True});self.assertEqual(a.software.execute(job)['verification'],'demo')
  with self.assertRaises(ValueError):a.software.consume({'token':p['token'],'confirmed':True})
 def test_software_rejects_changed_uninstaller(self):
  a=self.app();a.software.scan();p=a.software.preview({'id':'demo-0','action':'remove'});job=a.software.consume({'token':p['token'],'confirmed':True});rows,notes=a.software.read();rows[0]['uninstall']='changed.exe'
  with patch.object(a.software,'read',return_value=(rows,notes)),self.assertRaises(ValueError):a.software.execute(job)
 def test_tool_selection_has_identity_and_type(self):
  a=self.app();a.demo=False;folder=self.root/'selected';folder.mkdir();s=a.toolbox.select(folder,'folder');self.assertEqual(a.toolbox.target({'selection':s['token']},'folder'),folder)
  with self.assertRaises(ValueError):a.toolbox.target({'selection':s['token']},'file')
  folder.rmdir();os.symlink(self.root,folder)
  with self.assertRaises(ValueError):a.toolbox.target({'selection':s['token']},'folder')
 def test_tool_cancel_does_not_save_incomplete_result(self):
  a=self.app()
  def cancelled(kind,body):a.toolbox.cancel.set();return dict(title='Not completed')
  with patch.object(a.toolbox,'demo',side_effect=cancelled):a.toolbox.start('processes',{});self.wait(a)
  self.assertIn('остановлена',a.toolbox.state['error']);self.assertFalse(a.toolbox.reports)
 def test_demo_tools_make_no_host_changes(self):
  a=self.app()
  for kind in ['processes','connections','network_chain','wifi','drive_health','battery','security','peripherals','printers','startup_extra','prepare_transfer']:
   with self.subTest(kind=kind):a.toolbox.start(kind,{'host':'example.com'});self.wait(a);self.assertIsNone(a.toolbox.state['error']);self.assertTrue(a.toolbox.state['result']['demo'])
  self.assertLessEqual(len(a.toolbox.reports),8);self.assertLessEqual(len(list(a.toolbox.directory.glob('result-*.json'))),8)

class ExtendedProductTests(unittest.TestCase):
 setUp=ProductTests.setUp
 tearDown=ProductTests.tearDown
 app=ProductTests.app
 wait=ProductTests.wait
 # Inherit the file fixtures, without re-running the parent test methods.
 def test_lease_gpu_values_are_sanitized(self):
  from winpilot.pc import vendor_metrics
  r=vendor_metrics({'gpu_details':[{'source':'NVML','name':'Card','key':'UUID','temperature_c':float('nan'),'load':101,'core_mhz':1800,'fan_percent':0,'clock_limit_bits':'8'}]})[0]
  self.assertIsNone(r['temperature_c']);self.assertIsNone(r['load']);self.assertEqual(r['core_mhz'],1800);self.assertEqual(r['fan_percent'],0)
 def test_authenticode_native_layout_matches_win64_sdk(self):
  from winpilot.trust import DATA,FILE,GUID
  self.assertEqual(C.sizeof(DATA),88);self.assertEqual(C.sizeof(FILE),32);self.assertEqual(C.sizeof(GUID),16)
 def test_watchdog_rejects_truncated_or_oversized_snapshots(self):
  import base64
  from winpilot.display_watchdog import decode
  from winpilot.display_advanced import PATH,MODE
  valid={'paths':base64.b64encode(bytes(C.sizeof(PATH))).decode(),'modes':base64.b64encode(bytes(C.sizeof(MODE))).decode()};p,m=decode(valid);self.assertEqual(len(p),1)
  for bad in ['invalid',base64.b64encode(b'x').decode(),base64.b64encode(bytes(C.sizeof(PATH)*129)).decode()]:
   with self.assertRaises(ValueError):decode({**valid,'paths':bad})
 def test_watchdog_unavailable_prevents_native_change(self):
  from winpilot import native
  g=native.DisplayGuard()
  with patch.object(native,'IS_WINDOWS',True),patch('winpilot.display_watchdog.Watchdog',side_effect=ValueError('Unavailable')),patch.object(native,'user32') as api,self.assertRaises(ValueError):g.apply('display','1920x1080@60',0)
  api.assert_not_called();self.assertIsNone(g.pending)
 def test_watchdog_worker_waits_for_parent_and_restores_on_death(self):
  from winpilot import display_watchdog as w
  from types import SimpleNamespace
  import io,base64,contextlib
  from winpilot.display_advanced import PATH,MODE
  snapshot={'paths':base64.b64encode(bytes(C.sizeof(PATH))).decode(),'modes':base64.b64encode(bytes(C.sizeof(MODE))).decode()}
  class K:
   def OpenProcess(self,*a):return 100
   def OpenEventW(self,*a):return 200
   def WaitForMultipleObjects(self,*a):return self.code
   def CloseHandle(self,*a):pass
  for code,restores in [(0,True),(1,False),(2,True),(258,True),(0xffffffff,True)]:
   k=K();k.code=code;data={'parent':123,'events':['Local\\KrolikDisplay-'+'a'*48,'Local\\KrolikDisplay-'+'b'*48],'snapshot':snapshot};out=io.StringIO()
   with patch.object(w,'kernel',return_value=k),patch.object(w.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(data).encode()+b'\n'))),patch.object(w,'restore') as restore,contextlib.redirect_stdout(out):self.assertEqual(w.worker(),0)
   self.assertEqual(restore.called,restores);self.assertIn('ready',out.getvalue())
 def test_recovery_infers_actual_moves_despite_stale_journal_counter(self):
  p=self.root/'old';p.write_text('one');identity=files.ident(p);temporary='.krolik-'+'a'*32+'.tmp';p.rename(self.root/temporary);j=self.root/'journal.json';atomic_json(j,dict(root=str(self.root),state='prepared',moved=0,committed=0,rows=[dict(before='old',after='new',temporary=temporary,identity=identity)]));job=files.recovery_plan(j);self.assertEqual(job['rows'][0]['before'],temporary);files.rename_apply(job,self.root/'recovery.json');self.assertEqual(p.read_text(),'one')
 def test_recovery_does_not_return_externally_changed_file(self):
  p=self.root/'new';p.write_text('one');identity=files.ident(p);j=self.root/'journal.json';atomic_json(j,dict(root=str(self.root),state='error',rows=[dict(before='old',after='new',temporary='.krolik-'+'a'*32+'.tmp',identity=identity)]));p.write_text('changed')
  with self.assertRaises(ValueError):files.recovery_plan(j)
 def test_new_rename_cannot_overwrite_unfinished_journal(self):
  a=self.app();a.demo=False;a.toolbox.select(self.root,'folder');atomic_json(a.toolbox.journal,{'state':'prepared'})
  with self.assertRaises(ValueError):a.toolbox.prepare({'kind':'rename'})
 def test_protected_rename_tree_rejected(self):
  p=self.root/'Windows/System32';p.mkdir(parents=True)
  with self.assertRaises(ValueError):files.rename_root(p,[self.root/'Windows'])
 def test_mixer_preview_external_change_is_rejected(self):
  a=self.app();m=a.mixer;m.scan();p=m.preview({'id':'demo-session','volume':30,'mute':False});m.rows[0]['volume']=40
  with self.assertRaises(ValueError):m.apply({'token':p['token']})
  self.assertEqual(m.rows[0]['volume'],40)
 def test_mixer_exact_change_undo_and_restart(self):
  from winpilot.mixer import Mixer
  a=self.app();m=a.mixer;m.scan();p=m.preview({'id':'demo-session','volume':30,'mute':True});r=m.apply({'token':p['token']});self.assertTrue(r['can_undo']);self.assertEqual(m.rows[0]['volume'],30);reopened=Mixer(a,self.root/'state');reopened.rows=copy.deepcopy(m.rows);self.assertTrue(reopened.scan()['can_undo']);reopened.undo({'confirmed':True});self.assertEqual(reopened.rows[0]['volume'],65);self.assertFalse(reopened.scan()['can_undo'])
 def test_mixer_never_accepts_bool_or_empty_volume(self):
  from winpilot.mixer import checked
  for value in [True,None,'',101,-1,float('nan')]:
   with self.assertRaises(ValueError):checked({'id':'id','volume':value,'mute':False})
 def test_task_changes_are_confirmed_single_use_and_reversible(self):
  a=self.app();t=a.startup_tasks;t.scan();p=t.preview({'id':'demo-task','enabled':False})
  with self.assertRaises(ValueError):t.apply({'token':p['token']})
  r=t.apply({'token':p['token'],'confirmed':True});self.assertTrue(r['can_undo']);self.assertFalse(r['items'][0]['enabled'])
  with self.assertRaises(ValueError):t.apply({'token':p['token'],'confirmed':True})
  t.undo({'confirmed':True});self.assertTrue(t.rows[0]['enabled']);self.assertFalse(t.scan()['can_undo'])
 def test_task_external_definition_change_prevents_write(self):
  a=self.app();t=a.startup_tasks;t.scan();p=t.preview({'id':'demo-task','enabled':False});t.rows[0]['xml_sha256']='c'*64
  with patch.object(t,'set') as write,self.assertRaises(ValueError):t.apply({'token':p['token'],'confirmed':True})
  write.assert_not_called()
 def test_system_tasks_are_read_only(self):
  a=self.app();t=a.startup_tasks;t.scan();t.rows[0]['controllable']=False
  with self.assertRaises(ValueError):t.preview({'id':'demo-task','enabled':False})
 def test_latency_does_not_invent_good_network_from_no_replies(self):
  from winpilot.network_tools import latency
  r=latency({'samples':[{'ok':False,'milliseconds':None}]*8});self.assertEqual(r['loss_percent'],100);self.assertIsNone(r['mean_ms']);self.assertIsNone(r['jitter_ms']);self.assertIsNone(latency({})['loss_percent'])
 def test_latency_jitter_uses_successive_reply_differences(self):
  from winpilot.network_tools import latency
  r=latency({'samples':[{'ok':True,'milliseconds':x} for x in [10,20,15]]});self.assertEqual(r['jitter_ms'],7.5);self.assertEqual(r['mean_ms'],15);self.assertEqual(r['received'],3)
 def test_network_no_dns_addresses_never_opens_a_socket(self):
  from winpilot.network_tools import connect
  with patch('socket.socket') as socket:r=connect('example.com',[],self.stop,self.stage)
  socket.assert_not_called();self.assertEqual(r[0]['status'],'unavailable')
 def test_tool_invalid_kind_is_a_user_validation_error(self):
  a=self.app()
  for kind in [[],{},True,None]:
   with self.assertRaises(ValueError):a.toolbox.start(kind,{})
 def test_new_demo_diagnostics_are_separate_from_real_hardware(self):
  a=self.app()
  for kind in ('latency','crashes','rename_recover'):
   a.toolbox.start(kind,{'host':'example.com','confirmed':True});self.wait(a);self.assertIsNone(a.toolbox.state['error']);self.assertTrue(a.toolbox.state['result']['demo'])


class FinalProductRegressions(unittest.TestCase):
 setUp=ProductTests.setUp
 tearDown=ProductTests.tearDown
 app=ProductTests.app
 wait=ProductTests.wait
 def test_shared_user_registry_view_is_one_installation(self):
  from winpilot.installed_apps import collapse_shared_user_views
  base={'registry_hive':'HKCU','registry_key':'Firefox','name':'Firefox','version':'140','uninstall':'same.exe','scope':'user'}
  rows=collapse_shared_user_views([{**base,'record_id':'64','architecture':'x64','registry_view':'x64','architecture_source':'registry_view'},{**base,'record_id':'32','architecture':'x86','registry_view':'x86','architecture_source':'registry_view'}]);self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['architecture']);self.assertEqual(rows[0]['registry_view'],'shared')
 def test_different_user_architecture_installs_remain_separate(self):
  from winpilot.installed_apps import collapse_shared_user_views
  base={'registry_hive':'HKCU','registry_key':'Firefox','name':'Firefox','version':'140','scope':'user'};rows=collapse_shared_user_views([{**base,'uninstall':'64.exe','architecture':'x64'},{**base,'uninstall':'32.exe','architecture':'x86'}]);self.assertEqual(len(rows),2)
 def test_transfer_profile_contains_current_values_and_is_importable(self):
  from winpilot.transfer import snapshot
  from winpilot.workspace import saved_plan
  a=self.app();a.info['settings']['mouse_speed']='13';r=snapshot(a.info,[{'name':'Mozilla Firefox','version':'140'}],['Drivers-1']);self.assertEqual(r['profile']['settings']['mouse_speed'],'13');saved_plan(r['profile']);saved_plan(r['reinstall_plan']);self.assertIn('Mozilla.Firefox',r['reinstall_plan']['apps']);self.assertNotIn('dns',r['profile']['settings']);self.assertNotIn('displays',r['profile'])
 def test_cache_records_hashes_and_never_starts_an_installer(self):
  from winpilot.offline import download
  from types import SimpleNamespace
  calls=[]
  def command(args,timeout):
   calls.append(args);folder=Path(args[args.index('--download-directory')+1]);(folder/'Installer.exe').write_bytes(b'official-download-fixture')
  backend=SimpleNamespace(prepare_package_manager=lambda:None,package_manager=SimpleNamespace(_command=command));r=download(backend,self.root,['Mozilla.Firefox'],threading.Event(),lambda _:None);manifest=json.loads((Path(r['path'])/'KrolikControl-cache.json').read_text());self.assertTrue(manifest['complete']);self.assertEqual(manifest['files'][0]['sha256'],hashlib.sha256(b'official-download-fixture').hexdigest());self.assertEqual(calls[0][0],'download');self.assertNotIn('--ignore-security-hash',calls[0])
 def test_cancelled_cache_does_not_bootstrap_or_create_a_folder(self):
  from winpilot.offline import download
  from unittest.mock import Mock
  backend=Mock();stop=threading.Event();stop.set()
  with self.assertRaises(files.Stopped):download(backend,self.root,['Mozilla.Firefox'],stop,lambda _:None)
  backend.prepare_package_manager.assert_not_called();self.assertEqual(list(self.root.iterdir()),[])
 def test_cache_failure_keeps_a_marked_incomplete_manifest(self):
  from winpilot.offline import download
  from types import SimpleNamespace
  def fail(args,timeout):raise ValueError('Download failed')
  b=SimpleNamespace(prepare_package_manager=lambda:None,package_manager=SimpleNamespace(_command=fail))
  with self.assertRaises(ValueError):download(b,self.root,['Mozilla.Firefox'],threading.Event(),lambda _:None)
  manifests=list(self.root.glob('KrolikOffline-*/KrolikControl-cache.json'));self.assertEqual(len(manifests),1);self.assertFalse(json.loads(manifests[0].read_text())['complete'])
 def test_async_rename_preview_does_not_block_the_control_api(self):
  a=self.app();a.toolbox.select(self.root,'folder');s=a.toolbox.state['selection'];started=time.monotonic();a.post('/api/tools/preview',{'kind':'rename','selection':s['token'],'find':'a','replace':'b'});self.assertLess(time.monotonic()-started,.15);self.wait(a);self.assertEqual(a.toolbox.state['result']['kind'],'rename_preview');self.assertFalse(a.toolbox.reports)
 def test_cache_plan_never_accepts_arbitrary_package_ids(self):
  a=self.app();a.toolbox.select(self.root,'folder');token=a.toolbox.state['selection']['token']
  for apps in [[],['Unknown.Package'],['Mozilla.Firefox','Mozilla.Firefox'],[None]]:
   with self.assertRaises(ValueError):a.toolbox.start('offline_cache',{'selection':token,'apps':apps,'confirmed':True})
 def test_tool_reports_are_lazy_and_loaded_by_known_identity(self):
  a=self.app();a.toolbox.start('processes',{});self.wait(a);r=a.state()['data']['toolbox'];self.assertNotIn('data',r['reports'][0]);self.assertIn('data',r['result']);a.toolbox.open_report(r['reports'][0]['id'])
  with self.assertRaises(ValueError):a.toolbox.open_report('../outside.json')
 def test_corrupt_new_tool_reports_do_not_hide_an_older_good_result(self):
  from winpilot.toolbox import Toolbox
  a=self.app();a.toolbox.start('processes',{});self.wait(a);original=a.toolbox.reports[0]['id']
  for i in range(10):(a.toolbox.directory/f'result-999999999999999999{i}.json').write_text('{bad')
  t=Toolbox(a,self.root/'state');self.addCleanup(t.close);self.assertEqual(t.reports[0]['id'],original)
 def test_nonfinite_saved_report_is_ignored_without_breaking_startup(self):
  from winpilot.toolbox import Toolbox
  a=self.app();atomic_json(a.toolbox.directory/'result-999.json',dict(kind='processes',title='Title',time=float('nan')));t=Toolbox(a,self.root/'state');self.addCleanup(t.close);self.assertFalse(t.reports)
 def test_external_unverified_operation_is_never_green(self):
  e=Engine(Demo(),self.root,False);e.external('Vendor operation',lambda:{'verification':'unverified','message':'Readback unavailable'});h=e.history[0];self.assertEqual(h['success'],0);self.assertEqual(h['closed'],1);self.assertEqual(h['items'][0]['verification'],'unverified')
 def test_external_journal_failure_prevents_the_action(self):
  from unittest.mock import Mock
  e=Engine(Demo(),self.root,False);fn=Mock()
  with patch('pathlib.Path.open',side_effect=OSError('Disk full')),self.assertRaises(OSError):e.external('Vendor operation',fn)
  fn.assert_not_called()
 def test_file_worker_protocol_runs_with_real_temp_file(self):
  import subprocess,sys
  p=self.root/'file';p.write_bytes(b'worker');s=p.stat();spec=self.root/'spec.json';atomic_json(spec,{'kind':'hash','target':str(p),'identity':[s.st_dev,s.st_ino]});r=subprocess.run([sys.executable,'-B','-m','winpilot.file_worker',str(spec)],capture_output=True,text=True,timeout=5);self.assertEqual(r.returncode,0,r.stderr);result=[json.loads(l) for l in r.stdout.splitlines() if json.loads(l)['phase']=='result'][0];self.assertEqual(result['result']['sha256'],hashlib.sha256(b'worker').hexdigest())
 def test_file_worker_rejects_a_replaced_selection(self):
  import subprocess,sys
  p=self.root/'file';p.write_bytes(b'worker');spec=self.root/'spec.json';atomic_json(spec,{'kind':'hash','target':str(p),'identity':[0,0]});r=subprocess.run([sys.executable,'-B','-m','winpilot.file_worker',str(spec)],capture_output=True,text=True,timeout=5);self.assertNotEqual(r.returncode,0);self.assertNotIn('"phase": "result"',r.stdout)
 def test_legacy_advanced_color_api_is_detected_separately_from_hdr(self):
  from winpilot import display_advanced as d
  class API:
   def DisplayConfigGetDeviceInfo(self,p):
    h=C.cast(p,C.POINTER(d.HEADER)).contents
    if h.type==15:return 87
    q=C.cast(p,C.POINTER(d.COLOR)).contents;q.flags=3;q.bits=10;return 0
  r=d.color(API(),d.PATH());self.assertTrue(r['hdr_available']);self.assertTrue(r['hdr_enabled']);self.assertEqual(r['hdr_api'],10);self.assertIn('WCG',r['control_label'])

if __name__=='__main__':unittest.main()
