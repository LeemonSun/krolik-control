import unittest
from winpilot.files import valid_name

class FilenameBoundaries(unittest.TestCase):
 def test_console_device_names_rejected(self):
  for name in ('CONIN$','CONOUT$','conin$.txt','ConOut$.log'):
   with self.subTest(name=name):self.assertFalse(valid_name(name))
 def test_length_counts_windows_utf16_units(self):
  self.assertTrue(valid_name('🙂'*100))
  self.assertFalse(valid_name('🙂'*101))
  self.assertTrue(valid_name('a'*200))
  self.assertFalse(valid_name('a'*201))
 def test_unpaired_surrogates_rejected_without_crash(self):
  self.assertFalse(valid_name('\ud800.txt'))
  self.assertFalse(valid_name('\udfff'))
