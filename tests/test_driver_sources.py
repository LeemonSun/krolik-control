import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from winpilot.demo import Demo, INFO
from winpilot.server import Application
from winpilot.driver_sources import amd_installer, recommended_sources, trusted_url, DriverSources, MAX_DOWNLOAD


class Response(io.BytesIO):
    def __init__(self, body, url='https://dsadata.intel.com/installer', headers=None):
        super().__init__(body); self.url = url; self.headers = headers or {}
    def geturl(self):return self.url


class DriverSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Application(Demo(), Path(__file__).resolve().parents[1] / 'ui', self.tmp.name, True)
        self.app.info = copy.deepcopy(INFO)
        self.center = self.app.driver_sources

    def tearDown(self):
        self.app.pc.close();self.app.toolbox.close();self.tmp.cleanup()

    def test_no_user_url_can_select_download(self):
        for url in ('http://dsadata.intel.com/installer', 'https://dsadata.intel.com.evil.test/file.exe',
                    'https://dsadata.intel.com@evil.test/file.exe', 'file:///C:/setup.exe',
                    'https://dsadata.intel.com:444/file.exe', 'https://user:password@dsadata.intel.com/file.exe'):
            with self.subTest(url=url), self.assertRaises(ValueError):trusted_url('intel', url)

    def test_manufacturer_match_does_not_select_actual_driver(self):
        rows = recommended_sources({'gpu': ['AMD Radeon RX 6650 XT'], 'cpu': ['Intel Core']}, [])
        self.assertTrue(next(r for r in rows if r['id'] == 'amd')['recommended'])
        self.assertTrue(next(r for r in rows if r['id'] == 'intel')['recommended'])
        self.assertFalse(next(r for r in rows if r['id'] == 'hp')['recommended'])

    def test_amd_page_requires_one_real_installer_link(self):
        url = 'https://drivers.amd.com/drivers/installer/26.20/beta/amd-software-minimalsetup-261029_web.exe'
        self.assertEqual(amd_installer(f'<a href="{url}">Download</a>'), url)
        for page in ('<a href="https://evil.test/setup.exe">download</a>',
                     '<a href="https://drivers.amd.com/drivers/setup.exe">download</a>',
                     f'<a href="{url}"></a><a href="{url.replace("261029", "261030")}"></a>'):
            with self.assertRaises(ValueError):amd_installer(page)

    def test_demo_neither_downloads_nor_opens_browser(self):
        with patch('winpilot.driver_sources.vendor_open') as opened, patch('webbrowser.open') as browser:
            result = self.center.download('intel');self.center.open_source('amd')
            self.assertTrue(result['demo']);opened.assert_not_called();browser.assert_not_called()

    def real_download(self, response):
        self.app.demo = False
        with patch('winpilot.driver_sources.vendor_open', return_value=response), patch.object(self.center, 'check_signature', return_value='Intel Corporation'):
            return self.center.download('intel')

    def test_download_is_verified_but_never_executed(self):
        body = b'MZ' + b'x' * 2046
        with patch('os.startfile') as start:
            result = self.real_download(Response(body, headers={'Content-Length': str(len(body))}))
            start.assert_not_called()
        self.assertEqual(result['sha256'], hashlib.sha256(body).hexdigest())
        self.assertTrue(self.center.ready[result['id']]['path'].is_file())

    def test_html_instead_of_installer_rejected(self):
        with self.assertRaises(ValueError):self.real_download(Response(b'<html>' + b'x' * 2000))
        self.assertFalse(list(self.center.directory.rglob('*.part')))
        self.assertFalse(self.center.ready)

    def test_short_or_oversized_response_rejected(self):
        for response in (Response(b'MZ'), Response(b'MZ' + b'x' * 2046, headers={'Content-Length': str(MAX_DOWNLOAD + 1)}),
                         Response(b'MZ' + b'x' * 2046, headers={'Content-Length': '4096'})):
            with self.assertRaises(ValueError):self.real_download(response)
        self.assertFalse(self.center.ready)

    def test_redirect_to_unapproved_host_rejected(self):
        with self.assertRaises(ValueError):self.real_download(Response(b'MZ' + b'x' * 2046, url='https://evil.test/a.exe'))

    def test_changed_download_cannot_launch(self):
        result = self.real_download(Response(b'MZ' + b'x' * 2046))
        self.center.ready[result['id']]['path'].write_bytes(b'changed')
        with patch('os.startfile') as start, self.assertRaises(ValueError):self.center.launch({'id': result['id'], 'confirmed': True})
        start.assert_not_called()

    def test_launch_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):self.center.launch({'id': 'made-up'})

    def test_invalid_producer_never_creates_task(self):
        for vendor in ('evil', 'https://evil.test/setup.exe', ['amd']):
            with self.assertRaises(ValueError):self.app.post('/api/driver-source/download', {'vendor': vendor, 'confirmed': True})
        self.assertNotIn('driver_download', self.app.tasks)

    def test_unrelated_valid_signature_is_not_accepted(self):
        self.app.backend.psjson = lambda *args, **kwargs: {'status': 'Valid', 'subject': 'CN=Another Company, O=Another Company'}
        with patch('winpilot.trust.verify'), self.assertRaises(ValueError):self.center.check_signature('example.exe', 'intel')

    def test_exact_expected_publisher_is_accepted(self):
        self.app.backend.psjson = lambda *args, **kwargs: {'status': 'Valid', 'subject': 'CN="Advanced Micro Devices, Inc.", O="Advanced Micro Devices, Inc.", C=US'}
        with patch('winpilot.trust.verify'):
            self.assertEqual(self.center.check_signature('example.exe', 'amd'), 'Advanced Micro Devices, Inc.')
