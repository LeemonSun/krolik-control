"""Failures found during the second interaction and diagnostic audit."""
import json,math,tempfile,time,unittest,threading
from pathlib import Path
from unittest.mock import patch
from winpilot.care import CareCenter,network_findings
from winpilot.server import Application
from winpilot.demo import Demo
from winpilot.workspace import atomic_json
from winpilot.benchmarks import interpret

class Audit(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=Application(Demo(),Path(__file__).parents[1]/'ui',self.tmp.name,True);self.app.info=self.app.backend.inventory();self.c=self.app.care
 def tearDown(self):self.tmp.cleanup()
 def report(self,**kw):return {'id':'valid','kind':'audio','title':'Audio report','time':time.time(),'findings':[],**kw}
 def test_workspace_retains_different_pending_values(self):
  w=self.app.workspace
  cases=[({'audio':[{'id':'a','volume':20}]},{'kind':'audio','key':'a','value':{'id':'a','volume':70}}),({'brightness':[{'id':'b','value':20}]},{'kind':'brightness','key':'b','value':70}),({'displays':[{'id':'d','mode':'1920x1080@60','orientation':0}]},{'kind':'display','key':'d','value':'1920x1080@144','orientation':0}),({'languages':['ru-RU','en-US']},{'kind':'languages','key':'languages','value':['en-US']}),({'startup':[{'id':'a'*64,'enabled':False}]},{'kind':'startup','key':'a'*64,'value':True})]
  for draft,op in cases:
   with self.subTest(kind=op['kind']):
    w.save({**w.value,'draft':draft});before=json.loads(json.dumps(w.value['draft']));w.clear_successes([{**op,'status':'success'}]);self.assertEqual(w.value['draft'],before)
 def test_finished_engine_reserves_readback_before_other_jobs(self):
  release=threading.Event();original=self.app._refresh_after_run
  def delayed(result):release.wait(2);original(result)
  try:
   with patch.object(self.app,'_refresh_after_run',side_effect=delayed):
    self.app.post('/api/apply',{'version':1,'settings':{'mouse_speed':'12'}});deadline=time.monotonic()+3
    while self.app.engine.snapshot()['running'] and time.monotonic()<deadline:time.sleep(.005)
    self.assertFalse(self.app.engine.snapshot()['running']);self.assertTrue(self.app.blocking_scan())
    with self.assertRaises(ValueError):self.app.post('/api/care/start',{'kind':'audio'})
  finally:release.set()
  deadline=time.monotonic()+3
  while self.app.blocking_scan() and time.monotonic()<deadline:time.sleep(.01)
 def test_matching_audio_choice_is_still_removed(self):
  w=self.app.workspace;w.save({**w.value,'draft':{'audio':[{'id':'a','volume':20}]}});w.clear_successes([{'kind':'audio','key':'a','value':{'volume':20,'id':'a'},'status':'success'}]);self.assertEqual(w.value['draft']['audio'],[])
 def test_legacy_fix_source_is_inferred_from_action(self):
  self.c.state['reports']=[self.report(kind='fix',findings=[{'id':'dns','title':'DNS','detail':'Failed','action':'dns_flush','level':'warning','target':None}])];p=self.c.preview('valid','dns');self.assertEqual(self.c.pending[p['token']]['source_kind'],'network')
 def test_unknown_network_checks_never_claim_success(self):
  for dns,https in [(None,None),(None,True),(True,None)]:
   with self.subTest(dns=dns,https=https):self.assertFalse(any(r['id']=='network_ok' for r in network_findings({'adapters':[{'up':True}],'dns':dns,'https':https})))
 def test_verified_network_still_reports_success(self):self.assertTrue(any(r['id']=='network_ok' for r in network_findings({'adapters':[{'up':True}],'dns':True,'https':True})))
 def test_broken_report_kind_does_not_break_startup(self):
  atomic_json(self.c.directory/'report-999.json',self.report(kind=[]));self.assertEqual(CareCenter(self.app).state['reports'],[])
 def test_invalid_report_shape_is_not_loaded(self):
  for bad in ({'samples':'broken'},{'metrics':[]},{'time':float('nan')},{'time':True},{'id':'<bad"id>'}):
   with self.subTest(bad=bad):atomic_json(self.c.directory/'report-999.json',self.report(**bad));self.assertEqual(CareCenter(self.app).state['reports'],[])
 def test_valid_older_report_survives_corrupt_recent_files(self):
  atomic_json(self.c.directory/'report-001.json',self.report())
  for i in range(10,20):(self.c.directory/f'report-{i:03}.json').write_text('broken JSON')
  self.assertEqual([r['id'] for r in CareCenter(self.app).state['reports']],['valid'])
 def test_unknown_kind_is_a_validation_error(self):
  for kind in ([],{},None,False):
   with self.subTest(kind=kind),self.assertRaises(ValueError):self.c.start(kind)
 def test_undo_updates_visible_and_saved_report(self):
  r=self.report(kind='fix',source_kind='audio',undo='mic_access');self.c.state['reports']=[r];atomic_json(self.c.directory/'report-001.json',r);atomic_json(self.c.directory/'last-repair-undo.json',{'kind':'mic_access','previous':'Deny','report':r['id']});revision=self.app.data_revision
  self.c.undo_last(r['id']);self.assertNotIn('undo',self.c.state['reports'][0]);self.assertTrue(self.c.state['reports'][0]['undo_applied']);self.assertGreater(self.app.data_revision,revision);self.assertNotIn('undo',CareCenter(self.app).state['reports'][0])
 def test_fix_report_stays_in_source_category(self):
  r=self.report(kind='network',findings=[{'id':'dns','title':'DNS','detail':'Failed','action':'dns_flush','level':'warning','target':None}]);self.c.state['reports']=[r];preview=self.c.preview(r['id'],'dns');self.c.fix(preview['token'])
  deadline=time.monotonic()+3
  while self.c.state['running'] and time.monotonic()<deadline:time.sleep(.01)
  self.assertEqual(self.c.state['reports'][0].get('source_kind'),'network')
 def test_cancelled_voice_is_removed_from_memory(self):
  def cancelled(c,k,b):c.voice={'data':b'test'};c.cancel.set();return {'title':'Voice','findings':[]}
  with patch('winpilot.care_windows.demo_run',side_effect=cancelled):
   self.c.start('voice',{'id':'demo-microphone','confirmed':True});deadline=time.monotonic()+3
   while self.c.state['running'] and time.monotonic()<deadline:time.sleep(.01)
  self.assertIsNone(self.c.voice);self.assertIsNone(self.c.state['voice_report'])
 def test_nonfinite_benchmark_is_unavailable(self):
  for value in (float('nan'),float('inf'),True):
   with self.subTest(value=value):m={'cpu_single_mloops':value};interpret(m);self.assertIsNone(m['cpu_single_mloops'])
 def test_disks_on_different_targets_are_not_compared(self):
  rows=interpret({'disk_read_mib_s':10,'disk_target':'D:\\'},{'disk_read_mib_s':100,'disk_target':'C:\\'});self.assertFalse(any(r['id']=='regression_disk_read_mib_s' for r in rows))
if __name__=='__main__':unittest.main()
