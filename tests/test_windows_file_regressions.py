import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from winpilot import files
from winpilot.pending import PendingChecks
from winpilot.workspace import atomic_json


class WindowsFileRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.stop = threading.Event()
    def tearDown(self):self.temp.cleanup()

    def test_folder_enumeration_uses_comparable_file_ids(self):
        for name in ('one', 'two'):(self.root/name).write_bytes(b'same')
        rows, _ = files.walk(self.root,self.stop,lambda _: None)
        for row in rows:self.assertEqual(row['identity'],files.ident(self.root/row['path']))
        result = files.duplicates(self.root,self.stop,lambda _: None)
        self.assertEqual(len(result['groups']),1)
        self.assertEqual(result['groups'][0]['sha256'],hashlib.sha256(b'same').hexdigest())

    def test_hard_links_count_once_without_symlink_privileges(self):
        (self.root/'original').write_bytes(b'x'*20)
        os.link(self.root/'original',self.root/'hardlink')
        result = files.analyze(self.root,self.stop,lambda _: None)
        self.assertEqual(result['bytes'],20)
        self.assertEqual(result['files'],1)

    def test_interrupted_cyrillic_rename_journal_recovers_original_filename(self):
        folder = self.root/'Фотографии';folder.mkdir()
        (folder/'старое фото.txt').write_text('данные',encoding='utf-8')
        plan=files.rename_preview(folder,'старое','новое')
        journal=self.root/'имена.json'
        files.rename_apply(plan,journal)
        # Simulate loss of the final completed marker after files have moved.
        saved=json.loads(journal.read_text(encoding='utf-8'));saved['state']='prepared'
        atomic_json(journal,saved)
        undo=files.recovery_plan(journal)
        files.rename_apply(undo,self.root/'возврат.json')
        self.assertEqual((folder/'старое фото.txt').read_text(encoding='utf-8'),'данные')

    def test_cyrillic_pending_check_survives_reopen(self):
        checks=PendingChecks(self.root)
        operation={'kind':'setting','key':'theme','value':'dark','title':'Тёмная тема'}
        checks.add(operation,'unverified','Проверка ещё не выполнена')
        reopened=PendingChecks(self.root)
        self.assertEqual(reopened.snapshot()[0]['message'],'Проверка ещё не выполнена')
        self.assertEqual(reopened.snapshot()[0]['operation']['title'],'Тёмная тема')
