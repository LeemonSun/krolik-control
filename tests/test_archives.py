import io
import os
import stat
import tempfile
from pathlib import Path
import threading
import unittest
import zipfile
import struct
from winpilot import archives

class Archives(unittest.TestCase):
 def test_highly_compressible_local_file_roundtrips(self):
  folder=self.root/'zero-data';folder.mkdir();(folder/'zeros.bin').write_bytes(b'\0'*(2*1024**2))
  result=archives.create(folder,self.stop)
  output=Path(archives.extract(Path(result['destination']),self.stop)['destination'])
  self.assertEqual((output/'zeros.bin').stat().st_size,2*1024**2)
 def test_hardlinked_names_are_both_preserved_in_archive(self):
  folder=self.root/'links';folder.mkdir();(folder/'one').write_bytes(b'content');os.link(folder/'one',folder/'two')
  result=archives.create(folder,self.stop)
  output=Path(archives.extract(Path(result['destination']),self.stop)['destination'])
  self.assertEqual((output/'one').read_bytes(),(output/'two').read_bytes())
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.stop=threading.Event()
 def tearDown(self):self.tmp.cleanup()
 def make(self,entries):
  p=self.root/'test.zip'
  with zipfile.ZipFile(p,'w') as z:
   for name,data in entries:
    entry=zipfile.ZipInfo(name);entry.filename=name;entry.orig_filename=name;z.writestr(entry,data)
  return p
 def test_unicode_roundtrip_and_empty_folder(self):
  folder=self.root/'Фото';folder.mkdir();(folder/'пустая').mkdir();(folder/'текст.txt').write_text('Привет 👋',encoding='utf-8')
  result=archives.create(folder,self.stop);archive=Path(result['destination'])
  self.assertEqual(archives.inspect(archive)['entries'],2)
  out=Path(archives.extract(archive,self.stop)['destination'])
  self.assertEqual((out/'текст.txt').read_text(encoding='utf-8'),'Привет 👋');self.assertTrue((out/'пустая').is_dir())
 def test_unsafe_names_never_create_output(self):
  for name in ('../escape','/absolute','C:/file','a\\b','CON.txt','a/../b','file.','x:stream'):
   with self.subTest(name=name):
    p=self.make([(name,b'bad')])
    with self.assertRaises(ValueError):archives.extract(p,self.stop)
    self.assertFalse((self.root/'test-unpacked').exists());self.assertFalse(list(self.root.glob('.krolik-unzip-*')))
 def test_duplicate_and_parent_file_collision(self):
  for entries in ([('a',b'1'),('A',b'2')],[('a',b'1'),('a/b',b'2')]):
   with self.assertRaises(ValueError):archives.inspect(self.make(entries))
 def test_symlink_entry_is_refused(self):
  p=self.root/'link.zip';entry=zipfile.ZipInfo('link');entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16
  with zipfile.ZipFile(p,'w') as z:z.writestr(entry,'outside')
  with self.assertRaises(ValueError):archives.inspect(p)
 def test_existing_result_is_preserved(self):
  p=self.make([('a',b'new')]);out=self.root/'test-unpacked';out.mkdir();(out/'a').write_bytes(b'old')
  with self.assertRaises(ValueError):archives.extract(p,self.stop)
  self.assertEqual((out/'a').read_bytes(),b'old')
 def test_cancellation_leaves_no_partial_result(self):
  p=self.make([('a',b'data')]);self.stop.set()
  with self.assertRaises(Exception):archives.extract(p,self.stop)
  self.assertFalse((self.root/'test-unpacked').exists());self.assertFalse(list(self.root.glob('.krolik-unzip-*')))
 def test_corrupt_zip_does_not_publish(self):
  p=self.root/'bad.zip';p.write_bytes(b'not a zip')
  with self.assertRaises((zipfile.BadZipFile,ValueError)):archives.extract(p,self.stop)
  self.assertFalse((self.root/'bad-unpacked').exists())
 def test_creation_does_not_overwrite_existing_archive(self):
  folder=self.root/'folder';folder.mkdir();target=self.root/'folder.zip';target.write_bytes(b'keep')
  with self.assertRaises(ValueError):archives.create(folder,self.stop)
  self.assertEqual(target.read_bytes(),b'keep')
 def test_false_directory_count_rejected_before_parsing(self):
  p=self.make([('a',b'data')]);raw=bytearray(p.read_bytes());end=raw.rfind(b'PK\x05\x06')
  struct.pack_into('<HH',raw,end+8,0,0);p.write_bytes(raw)
  with self.assertRaises(ValueError):archives.inspect(p)
 def test_declared_huge_member_is_refused(self):
  p=self.make([('a',b'data')]);raw=bytearray(p.read_bytes());central=raw.find(b'PK\x01\x02')
  struct.pack_into('<L',raw,central+24,archives.MAX_FILE+1);p.write_bytes(raw)
  with self.assertRaises(ValueError):archives.inspect(p)
 def test_compression_ratio_bomb_is_refused(self):
  p=self.root/'bomb.zip'
  with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('zeros',b'\0'*(2*1024**2))
  with self.assertRaises(ValueError):archives.extract(p,self.stop)
  self.assertFalse((self.root/'bomb-unpacked').exists())
 def test_crc_corruption_never_publishes_partial_folder(self):
  p=self.make([('a',b'UNIQUE_CONTENT')]);p.write_bytes(p.read_bytes().replace(b'UNIQUE_CONTENT',b'CORRUPTCONTENT'))
  with self.assertRaises(zipfile.BadZipFile):archives.extract(p,self.stop)
  self.assertFalse((self.root/'test-unpacked').exists())
 def test_preview_token_is_single_use_and_inspect_cannot_extract(self):
  from winpilot.server import Application
  from winpilot.demo import Demo,INFO
  app=Application(Demo(),Path(__file__).parents[1]/'ui',self.root/'state',True)
  try:
   app.info=INFO;app.demo=False
   p=self.make([('a',b'data')]);selection=app.toolbox.select(p,'file')
   preview=app.archives.preview({'action':'inspect','selection':selection['token']})
   with self.assertRaises(ValueError):app.archives.run({'token':preview['token'],'confirmed':True})
   self.assertFalse((self.root/'test-unpacked').exists())
   preview=app.archives.preview({'action':'extract','selection':selection['token']})
   with self.assertRaises(ValueError):app.archives.run({'token':preview['token']})
   result=app.archives.run({'token':preview['token'],'confirmed':True})
   self.assertTrue(Path(result['destination']).is_dir())
   with self.assertRaises(ValueError):app.archives.run({'token':preview['token'],'confirmed':True})
  finally:app.pc.close();app.toolbox.close()
