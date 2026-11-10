import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from winpilot.packages import (PackageManager,PackageError,SetupError,ProcessError,UserCancelled,release_assets,download_verified,verify_bundle,unpack_dependencies,safe_url,BUNDLE,DEPENDENCIES,PUBLISHER)
from winpilot.installed_apps import local_inventory,match_app
from winpilot.demo import Demo,INFO
from winpilot.engine import Engine,validate_plan,operations
from winpilot.server import Application
from winpilot.windows import Windows


def metadata():
    return {'draft':False,'prerelease':False,'tag_name':'v1.20.123','assets':[{'name':name,'browser_download_url':f'https://github.com/microsoft/winget-cli/releases/download/v1.20.123/{name}','size':100,'digest':'sha256:'+'a'*64} for name in (BUNDLE,DEPENDENCIES)]}


def appx(name='Microsoft.UI.Xaml.2.8',arch='x64',publisher=PUBLISHER,bundle=False):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w') as z:z.writestr('AppxMetadata/AppxBundleManifest.xml' if bundle else 'AppxManifest.xml',f'<Package xmlns="urn:test"><Identity Name="{name}" ProcessorArchitecture="{arch}" Publisher="{publisher}"/></Package>')
    return result.getvalue()


def wait(e):
    end=time.monotonic()+4
    while e.snapshot()['running'] and time.monotonic()<end:time.sleep(.01)
    assert not e.snapshot()['running']

class TrustAndDownload(unittest.TestCase):
    def test_stable_release_assets(self):self.assertEqual(set(release_assets(metadata())),{BUNDLE,DEPENDENCIES})
    def test_preview_and_unhashed_assets_rejected(self):
        for field,value in [('prerelease',True),('draft',True),('tag_name','v1.0-preview')]:
            raw=metadata();raw[field]=value
            with self.subTest(field=field),self.assertRaises(SetupError):release_assets(raw)
        raw=metadata();raw['assets'][0].pop('digest')
        with self.assertRaises(SetupError):release_assets(raw)
    def test_same_filename_on_wrong_repository_rejected(self):
        raw=metadata();raw['assets'][0]['browser_download_url']=raw['assets'][0]['browser_download_url'].replace('/microsoft/','/another-owner/')
        with self.assertRaises(SetupError):release_assets(raw)
    def test_http_or_untrusted_redirect_host_rejected(self):
        for url in ['http://github.com/microsoft/winget-cli','https://evil.test/file','https://github.com@evil.test/file','https://github.com:9999/file']:
            with self.subTest(url=url),self.assertRaises(SetupError):safe_url(url)
    def test_download_hash_and_size_checked(self):
        data=b'official-package';asset={'url':'https://github.com/test','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'package.msixbundle';progress=[]
            download_verified(asset,path,progress.append,opener=lambda _:io.BytesIO(data));self.assertEqual(path.read_bytes(),data);self.assertTrue(progress)
    def test_corrupt_or_truncated_download_is_never_promoted(self):
        for data in [b'bad',b'toolong'*50]:
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'package';asset={'url':'https://github.com/test','size':10,'sha256':'a'*64}
                with self.assertRaises(SetupError):download_verified(asset,path,lambda _:None,opener=lambda _:io.BytesIO(data))
                self.assertEqual(list(Path(d).iterdir()),[])
    def test_cancelled_download_removes_partial(self):
        cancel=threading.Event();cancel.set()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'package';asset={'url':'https://github.com/test','size':10,'sha256':'a'*64}
            with self.assertRaises(UserCancelled):download_verified(asset,path,lambda _:None,cancel,lambda _:io.BytesIO(b'1234567890'))
            self.assertFalse(path.exists());self.assertFalse(path.with_suffix('.part').exists())
    def test_bundle_identity_and_publisher_checked(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/BUNDLE;path.write_bytes(appx('Microsoft.DesktopAppInstaller',bundle=True));verify_bundle(path)
            path.write_bytes(appx('Another.App',bundle=True))
            with self.assertRaises(SetupError):verify_bundle(path)
            path.write_bytes(appx('Microsoft.DesktopAppInstaller',publisher='CN=Other',bundle=True))
            with self.assertRaises(SetupError):verify_bundle(path)
    def test_dependencies_only_target_architecture(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'deps.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('x64/ui.appx',appx());z.writestr('x86/ui.appx',appx(arch='x86'));z.writestr('arm64/ui.appx',appx(arch='arm64'))
            paths=unpack_dependencies(path,Path(d)/'out');self.assertEqual(len(paths),1);self.assertTrue(Path(paths[0]).exists())
    def test_dependency_traversal_and_wrong_identity_rejected(self):
        for member,data in [('../escape.appx',appx()),('x64/other.appx',appx('Another.App'))]:
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'deps.zip'
                with zipfile.ZipFile(path,'w') as z:z.writestr(member,data)
                with self.assertRaises(SetupError):unpack_dependencies(path,Path(d)/'out')
                self.assertFalse((Path(d)/'escape.appx').exists())

class InstallReliability(unittest.TestCase):
    def setUp(self):self.backend=Windows();self.manager=self.backend.package_manager;self.manager.path='winget.exe'
    def test_present_manager_is_not_downloaded(self):
        with patch.object(self.manager,'resolve',return_value='winget.exe'),patch('winpilot.packages.open_official',side_effect=AssertionError('no download')):
            self.assertTrue(self.manager.prepare()['ready'])
    def test_registration_repair_precedes_download(self):
        with patch.object(self.manager,'resolve',return_value=None),patch.object(self.manager,'_registered',return_value='registered-winget'),patch('winpilot.packages.open_official',side_effect=AssertionError('no download')):
            self.assertTrue(self.manager.prepare()['ready'])
    def test_unknown_package_never_runs(self):
        with patch.object(self.manager,'ready',side_effect=AssertionError('must validate first')):
            with self.assertRaises(ValueError):self.manager.install('evil.exe')
    def test_network_failure_during_detection_does_not_install(self):
        with patch.object(self.manager,'ready',return_value={'ready':True}),patch.object(self.manager,'_command',side_effect=ProcessError(0x80072ee7,'network failure')) as run:
            with self.assertRaisesRegex(PackageError,'интернет'):self.manager.install('Mozilla.Firefox')
            self.assertEqual(run.call_count,1)
    def test_only_known_absence_starts_install_then_readback(self):
        with patch.object(self.manager,'ready',return_value={'ready':True}),patch.object(self.manager,'_command',side_effect=[ProcessError(0x8a150014), 'installer done', 'installed']) as run:
            result=self.manager.install('Mozilla.Firefox');self.assertTrue(result['installed']);self.assertEqual(run.call_count,3)
            self.assertEqual(run.call_args_list[1].args[0][0],'install');self.assertEqual(run.call_args_list[2].args[0][0],'list')
    def test_false_success_is_rejected_on_readback(self):
        with patch.object(self.manager,'ready',return_value={'ready':True}),patch.object(self.manager,'_command',side_effect=[ProcessError(0x8a150014),'done',ProcessError(0x8a150014)]):
            with self.assertRaisesRegex(PackageError,'пока не найдена'):self.manager.install('Mozilla.Firefox')
    def test_reboot_result_is_retained(self):
        with patch.object(self.manager,'ready',return_value={'ready':True}),patch.object(self.manager,'_command',side_effect=[ProcessError(0x8a150014),ProcessError(0x8a150109)]):self.assertTrue(self.manager.install('Mozilla.Firefox')['reboot'])
    def test_no_applicable_upgrade_is_not_claimed_as_updated(self):
        with patch.object(self.manager,'ready',return_value={'ready':True}),patch.object(self.manager,'_command',side_effect=ProcessError(0x8a15002b)):
            result=self.manager.upgrade('Mozilla.Firefox');self.assertIn('не предложено',result['message'])
    def test_signed_exit_code_is_normalized(self):self.assertEqual(ProcessError(-1978335212).code,0x8a150014)

class FastInventoryTests(unittest.TestCase):
    def test_local_inventory_covers_names_without_shell_or_winget(self):
        rows=local_inventory([{'name':'Mozilla Firefox 144.0 (x64 ru)','version':'144.0'},{'name':'Opera GX Stable 120.0','version':'120.0'},{'name':'Steam','version':'2.0'},{'name':'Unknown app','version':'1'}])
        by_id={r['id']:r for r in rows};self.assertTrue(by_id['Mozilla.Firefox']['installed']);self.assertTrue(by_id['Opera.OperaGX']['installed']);self.assertFalse(by_id['Opera.Opera']['installed']);self.assertEqual(by_id['Valve.Steam']['update_check'],'not_checked')
    def test_name_substrings_are_not_installed_matches(self):
        for name in ['Steam Cleaner','Not Brave','Opera GX Helper','Chrome extension','VLC skin']:
            with self.subTest(name=name):self.assertIsNone(match_app(name))
    def test_initial_inventory_does_not_contact_the_package_catalog(self):
        with patch('winpilot.installed_apps.registered_apps',return_value=[{'name':'Steam','version':'2'}]),patch.object(Windows,'run',side_effect=AssertionError('shell is unnecessary')):
            rows=Windows().local_programs();self.assertTrue(next(r for r in rows if r['id']=='Valve.Steam')['installed'])
    def test_failed_update_scan_keeps_locally_found_programs(self):
        from winpilot.maintenance import program_inventory
        backend=Windows()
        with patch('winpilot.installed_apps.registered_apps',return_value=[{'name':'Steam','version':'2'}]),patch.object(backend.package_manager,'resolve',return_value='winget.exe'),patch.object(backend.package_manager,'_command',side_effect=ProcessError(0x80072ee7)):
            rows=program_inventory(backend)
        steam=next(r for r in rows if r['id']=='Valve.Steam');self.assertTrue(steam['installed']);self.assertEqual(steam['update_check'],'unavailable')

class QueueSetupTests(unittest.TestCase):
    def test_clean_windows_plan_includes_setup_before_apps(self):
        info={**copy.deepcopy(INFO),'winget':False};p=validate_plan({'apps':['Mozilla.Firefox']},info,[],demo=True)
        self.assertEqual([o['kind'] for o in operations(p,info,[])],['package_manager','app'])
    def test_standalone_preparation_is_explicit_boolean(self):
        validate_plan({'prepare_apps':True},INFO,[],demo=True)
        with self.assertRaises(ValueError):validate_plan({'prepare_apps':'yes'},INFO,[],demo=True)
    def test_setup_failure_skips_apps_and_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as d:
            backend=Demo();e=Engine(backend,d,False);info={**copy.deepcopy(INFO),'winget':False}
            with patch.object(backend,'prepare_package_manager',side_effect=SetupError('offline')),patch.object(backend,'install_app',create=True) as install,patch.object(backend,'reg_snapshot',create=True,return_value=[]),patch.object(backend,'apply_setting',create=True) as setting:
                e.start({'apps':['Mozilla.Firefox','Google.Chrome'],'settings':{'extensions':'on'}},info,[]);wait(e)
                install.assert_not_called();setting.assert_called_once();items=e.snapshot()['items'];self.assertEqual(items[0]['status'],'error');self.assertEqual([i['status'] for i in items if i['kind']=='app'],['skipped','skipped']);self.assertEqual(next(i for i in items if i['kind']=='setting')['status'],'success')
    def test_cancelled_setup_stops_queue_without_error(self):
        with tempfile.TemporaryDirectory() as d:
            backend=Demo();e=Engine(backend,d,False);info={**copy.deepcopy(INFO),'winget':False}
            with patch.object(backend,'prepare_package_manager',side_effect=UserCancelled('stopped')),patch.object(backend,'install_app',create=True) as install:
                e.start({'apps':['Mozilla.Firefox']},info,[]);wait(e);install.assert_not_called();self.assertTrue(all(i['status']=='skipped' for i in e.snapshot()['items']))
    def test_demo_missing_manager_can_install_after_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            backend=Demo();backend.info['winget']=False;app=Application(backend,Path(__file__).parents[1]/'ui',d,True);app.info=backend.inventory()
            preview=app.post('/api/preview',{'apps':['Opera.Opera']});self.assertFalse(backend.info['winget']);self.assertEqual(len(preview['operations']),2)
            app.post('/api/apply',{'apps':['Opera.Opera']});wait(app.engine);self.assertTrue(backend.info['winget']);self.assertIn('Opera.Opera',backend.installed)

if __name__=='__main__':unittest.main()
