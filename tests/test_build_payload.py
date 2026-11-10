import tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from build_portable import write_payload
class Payload(unittest.TestCase):
 def test_closed_archive_contains_exact_source_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'product';root.mkdir();(root/'file.txt').write_bytes(b'payload contents');target=Path(d)/'bundle.zip';write_payload(root,target)
   with zipfile.ZipFile(target) as z:self.assertIsNone(z.testzip());self.assertEqual(z.read('KrolikControl/file.txt'),b'payload contents')
   self.assertFalse(target.with_name(target.name+'.partial').exists())
 def test_interrupted_write_preserves_previous_archive(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'product';root.mkdir();(root/'file.txt').write_bytes(b'new payload');target=Path(d)/'bundle.zip';target.write_bytes(b'previous verified payload')
   with patch.object(zipfile.ZipFile,'write',side_effect=OSError('Interrupted write')),self.assertRaises(OSError):write_payload(root,target)
   self.assertEqual(target.read_bytes(),b'previous verified payload');self.assertFalse(target.with_name(target.name+'.partial').exists())
if __name__=='__main__':unittest.main()
