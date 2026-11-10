import unittest
from winpilot.catalog import APPS
from winpilot.installed_apps import ALIASES,match_app,local_inventory

class CatalogDetection(unittest.TestCase):
 def test_every_catalog_app_has_local_detection(self):
  self.assertFalse(set(APPS)-set(ALIASES))
 def test_installed_winrar_variants_match(self):
  for name in ('WinRAR','WinRAR 7.13 (64-bit)','WinRAR 7.13 (32-bit)','WinRAR (64-bit)'):
   with self.subTest(name=name):self.assertEqual(match_app(name),'RARLab.WinRAR')
 def test_similarly_named_programs_do_not_match(self):
  for name in ('WinRAR Updater','Fake WinRAR','WinRARHelper'):
   self.assertIsNone(match_app(name))
 def test_inventory_marks_existing_winrar_installed(self):
  rows=local_inventory([{'name':'WinRAR 7.13 (64-bit)','version':'7.13','scope':'machine','architecture':'x64'}])
  result=next(row for row in rows if row['id']=='RARLab.WinRAR')
  self.assertTrue(result['installed']);self.assertEqual(result['version'],'7.13')
