import unittest
from unittest.mock import Mock
from winpilot.admin_helper import validate_intent,validate_channel,execute,PIPE_PREFIX


class PrivilegeTests(unittest.TestCase):
    def test_closed_verbs_reject_commands_and_paths(self):
        for intent in ({'verb':'run','value':'cmd.exe'}, {'verb':'probe','value':{'command':'echo test'}}, {'verb':'driver_backup','value':{'path':'C:/'}}, {'verb':'update','value':{'id':'https://example.com','revision':1}}, {'verb':'time_zone','value':'UTC; echo nope'}):
            with self.subTest(intent=intent),self.assertRaises(ValueError):validate_intent(intent)

    def test_dns_requires_exact_identity_and_supported_choice(self):
        valid={'verb':'dns','value':{'adapter':1,'guid':'12345678-1234-1234-1234-123456789012','choice':'auto'}}
        self.assertEqual(validate_intent(valid),valid)
        for key,value in [('adapter',True),('guid',''),('choice','custom'),('choice',['auto'])]:
            bad={'verb':'dns','value':{**valid['value'],key:value}}
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_intent(bad)

    def test_invalid_envelopes_never_execute(self):
        backend=Mock();backend.is_admin.return_value=True
        for data in (None,[],{}, {'verb':'probe'}, {'verb':'probe','value':{},'script':'x'}):
            with self.assertRaises(ValueError):execute(backend,data)
        backend.restore_point.assert_not_called();backend.apply_setting.assert_not_called()

    def test_no_admin_cannot_execute(self):
        backend=Mock();backend.is_admin.return_value=False
        with self.assertRaises(ValueError):execute(backend,{'verb':'restore_point','value':{}})
        backend.restore_point.assert_not_called()

    def test_adapter_replacement_blocks_change(self):
        backend=Mock();backend.is_admin.return_value=True;backend.psjson.return_value='00000000-0000-0000-0000-000000000000'
        with self.assertRaisesRegex(ValueError,'изменился'):
            execute(backend,{'verb':'dns','value':{'adapter':1,'guid':'12345678-1234-1234-1234-123456789012','choice':'google'}})
        backend.apply_setting.assert_not_called()

    def test_channel_is_local_and_unambiguous(self):
        args=[PIPE_PREFIX+'a'*48,'b'*64,'c'*64,'S-1-5-21-123','1234']
        validate_channel(*args)
        for index,value in ((0,r'\\remote\pipe\KrolikAdmin-'+'a'*48),(1,'short'),(2,'xyz'),(3,'other'),(4,'0')):
            bad=args.copy();bad[index]=value
            with self.assertRaises(ValueError):validate_channel(*bad)
