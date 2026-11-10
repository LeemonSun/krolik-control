import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from winpilot.demo import Demo
from winpilot.engine import Engine,validate_plan,operations
from winpilot.profile_audio import default_id
from winpilot.recovery import checked_undo
from winpilot.workspace import saved_plan


class ProfileAudioTests(unittest.TestCase):
    def setUp(self):
        self.info=Demo().inventory()
        self.row={'id':self.info['endpoints'][0]['id'],'flow':0,'role':1}
        self.plan={'version':1,'audio_defaults':[self.row],'audio_routing_ack':True}

    def test_profile_roundtrip_and_operations(self):
        self.assertEqual(saved_plan(self.plan),self.plan)
        validate_plan(self.plan,self.info,[],demo=True)
        op=operations(self.plan,self.info,[])[0]
        self.assertEqual((op['kind'],op['key'],op['value']),('audio_default',self.row['id'],self.row))

    def test_missing_device_blocks_whole_plan(self):
        self.plan['audio_defaults'][0]['id']='disconnected'
        with self.assertRaisesRegex(ValueError,'отключено'):
            validate_plan(self.plan,self.info,[],demo=True)

    def test_invalid_values_and_duplicate_roles(self):
        invalid=[{'flow':True},{'role':True},{'role':3},{'flow':2},{'id':[]},{'extra':1}]
        for changes in invalid:
            p=copy.deepcopy(self.plan);p['audio_defaults'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):saved_plan(p)
        p=copy.deepcopy(self.plan);p['audio_defaults']*=2
        with self.assertRaises(ValueError):saved_plan(p)
        p=copy.deepcopy(self.plan);p.pop('audio_routing_ack')
        with self.assertRaises(ValueError):saved_plan(p)

    def test_role_snapshot_uses_flow_and_explicit_roles(self):
        rows=[{'id':'output','flow':0,'default_roles':[1]}, {'id':'mic','flow':1,'default_roles':[1,2]}]
        self.assertEqual(default_id(rows,1,2),'mic')
        self.assertIsNone(default_id(rows,0,2))

    def test_undo_written_before_change_and_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=Engine(Demo(),Path(temp));seen=[]
            op=operations(self.plan,self.info,[])[0]
            def change(*args):
                self.assertEqual(engine.undo[-1]['value'],'previous')
                self.assertTrue((Path(temp)/'last-settings-backup.json').is_file())
                seen.append(args)
            with patch('winpilot.profile_audio.read_default',return_value='previous'),patch('winpilot.profile_audio.set_role',side_effect=change):
                engine._apply(op,self.info)
            self.assertEqual(seen,[(self.row['id'],0,1)])
            checked_undo(engine.undo)

    def test_failed_change_reports_failed_return(self):
        with tempfile.TemporaryDirectory() as temp:
            engine=Engine(Demo(),temp);op=operations(self.plan,self.info,[])[0]
            with patch('winpilot.profile_audio.read_default',return_value='previous'),patch('winpilot.profile_audio.set_role',side_effect=OSError('offline')):
                with self.assertRaisesRegex(ValueError,'тоже не подтверждён'):engine._apply(op,self.info)
            self.assertEqual(engine.undo[-1]['value'],'previous')
