import ctypes as C
import copy
import time
import unittest
from unittest.mock import patch
from winpilot import native

class FakeAPI:
    def __init__(self): self.calls=[];self.commit_fails=False;self.test_fails=False
    def EnumDisplaySettingsW(self,device,index,pointer):
        if index not in (0,0xffffffff):return False
        dm=C.cast(pointer,C.POINTER(native.DEVMODE)).contents
        dm.width=1920;dm.height=1080;dm.hz=60 if index==0xffffffff else 144;dm.bpp=32
        dm.display.orientation=0;dm.display.position.x=100;dm.display.position.y=0
        return True
    def ChangeDisplaySettingsExW(self,device,pointer,hwnd,flags,param):
        dm=C.cast(pointer,C.POINTER(native.DEVMODE)).contents
        self.calls.append((device,dm.width,dm.height,dm.hz,flags,dm.display.position.x))
        if flags==2 and self.test_fails:return -2
        if flags==1 and self.commit_fails:return -1
        return 0

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeAPI();self.mock=patch.object(native,'user32',return_value=self.api);self.mock.start()
        self.timer=patch.object(native.threading,'Timer');self.timer.start();self.guard=native.DisplayGuard()
    def tearDown(self): self.guard.restore_pending();self.timer.stop();self.mock.stop()
    def test_preflight_before_apply(self):
        self.guard.apply('display','1920x1080@144',0)
        self.assertEqual([c[4] for c in self.api.calls],[2,0]);self.assertEqual(self.api.calls[0][5],100)
    def test_unsupported_mode_does_not_apply(self):
        with self.assertRaises(ValueError):self.guard.apply('display','1920x1080@999',0)
        self.assertEqual(self.api.calls,[])
    def test_test_failure_never_switches(self):
        self.api.test_fails=True
        with self.assertRaises(RuntimeError):self.guard.apply('display','1920x1080@144',0)
        self.assertEqual(len(self.api.calls),1)
    def test_confirm_saves(self):
        ident=self.guard.apply('display','1920x1080@144',0)
        self.assertTrue(self.guard.resolve(ident,True));self.assertEqual(self.api.calls[-1][4],1);self.assertIsNone(self.guard.status())
    def test_timeout_restores_old(self):
        ident=self.guard.apply('display','1920x1080@144',0)
        self.guard.resolve(ident,False)
        self.assertEqual(self.api.calls[-1][3],60);self.assertEqual(self.api.calls[-1][4],0)
    def test_commit_failure_restores_old(self):
        ident=self.guard.apply('display','1920x1080@144',0);self.api.commit_fails=True
        self.assertFalse(self.guard.resolve(ident,True));self.assertEqual(self.api.calls[-1][3],60)
    def test_wrong_confirmation_ignored(self):
        ident=self.guard.apply('display','1920x1080@144',0)
        self.assertFalse(self.guard.resolve('wrong',True));self.assertEqual(self.guard.status()['id'],ident)
    def test_late_confirmation_reverts(self):
        ident=self.guard.apply('display','1920x1080@144',0);self.guard.pending['deadline']=time.monotonic()-1
        self.assertFalse(self.guard.resolve(ident,True));self.assertEqual(self.api.calls[-1][3],60)
    def test_portrait_swaps_dimensions(self):
        self.guard.apply('display','1920x1080@144',1)
        self.assertEqual(self.api.calls[-1][1:3],(1080,1920))
    def test_second_display_waits_for_confirmation(self):
        self.guard.apply('display','1920x1080@144',0)
        with self.assertRaises(ValueError):self.guard.apply('other','1920x1080@144',0)

if __name__=='__main__':unittest.main()
