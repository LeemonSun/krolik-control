"""Real NTFS directory-link checks; no developer mode or symlink privilege needed."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from winpilot.files import analyze
from winpilot.storage import StorageCenter


@unittest.skipUnless(os.name=='nt','NTFS junction checks run on Windows')
class JunctionProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.links=[]
        self.script=self.root/'junction.ps1'
        self.script.write_text("param([string]$Link,[string]$Target)\n$ErrorActionPreference='Stop'\nNew-Item -ItemType Junction -Path $Link -Target $Target | Out-Null\n",encoding='utf-8')
    def tearDown(self):
        for link in reversed(self.links):
            if link.is_dir():link.rmdir() # Remove only the junction entry, never the target.
        self.tmp.cleanup()
    def junction(self,link,target):
        self.assertTrue(link.absolute().is_relative_to(self.root))
        self.assertTrue(target.resolve().is_relative_to(self.root))
        subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
            '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(self.script),str(link),str(target)],
            check=True,capture_output=True,timeout=10,creationflags=0x08000000)
        self.links.append(link)
        self.assertTrue(link.lstat().st_file_attributes & 0x400)
    def test_folder_analysis_never_follows_junction(self):
        selected=self.root/'selected';selected.mkdir();outside=self.root/'outside';outside.mkdir()
        (selected/'own').write_bytes(b'own');(outside/'keep').write_bytes(b'outside')
        self.junction(selected/'link',outside)
        result=analyze(selected,threading.Event(),lambda _:None)
        self.assertEqual(result['bytes'],3);self.assertEqual(result['files'],1)
        self.assertGreaterEqual(result['skipped'],1);self.assertTrue((outside/'keep').exists())
    def test_cleanup_preview_never_follows_junction(self):
        selected=self.root/'Temp';selected.mkdir();outside=self.root/'outside';outside.mkdir()
        keep=outside/'keep';keep.write_bytes(b'data');os.utime(keep,(time.time()-9*86400,)*2)
        self.junction(selected/'link',outside)
        center=StorageCenter(SimpleNamespace(demo=False),selected)
        snapshot=center.scan();self.assertEqual(snapshot['files'],0);self.assertTrue(keep.exists())
    def test_parent_replaced_by_junction_after_preview_is_not_deleted(self):
        selected=self.root/'Temp';selected.mkdir();sub=selected/'sub';sub.mkdir()
        keep=sub/'keep';keep.write_bytes(b'data');os.utime(keep,(time.time()-9*86400,)*2)
        center=StorageCenter(SimpleNamespace(demo=False),selected);snapshot=center.scan()
        original=selected/'original';sub.rename(original);self.junction(sub,original)
        result=center.clean(center.consume({'token':snapshot['token'],'confirmed':True}))
        self.assertEqual(result['deleted'],0);self.assertEqual(result['skipped'],1)
        self.assertTrue((original/'keep').exists())
