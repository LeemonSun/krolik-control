"""Manufacturer support routes and signed vendor setup downloads.

Never choose a driver by a fuzzy device name or accept a URL from the UI.
"""
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request

SOURCES = {
    'amd': ('AMD', 'https://www.amd.com/en/support/download/drivers.html', 'Radeon / Ryzen'),
    'nvidia': ('NVIDIA', 'https://www.nvidia.com/en-us/drivers/', 'GeForce / RTX / Quadro'),
    'intel': ('Intel', 'https://www.intel.com/content/www/us/en/support/detect.html', 'Graphics / Wi-Fi / Bluetooth / Ethernet'),
    'dell': ('Dell', 'https://www.dell.com/support/home/en-us?app=drivers', 'PC / notebook'),
    'hp': ('HP', 'https://support.hp.com/drivers', 'PC / notebook / printer'),
    'lenovo': ('Lenovo', 'https://pcsupport.lenovo.com/products', 'PC / notebook'),
    'asus': ('ASUS', 'https://www.asus.com/support/download-center/', 'Motherboard / notebook'),
    'msi': ('MSI', 'https://www.msi.com/support', 'Motherboard / notebook'),
    'gigabyte': ('GIGABYTE', 'https://www.gigabyte.com/Support', 'Motherboard / notebook'),
    'asrock': ('ASRock', 'https://www.asrock.com/support/index.asp', 'Motherboard'),
    'realtek': ('Realtek', 'https://www.realtek.com/Download/Index', 'Audio / Ethernet'),
    'broadcom': ('Broadcom', 'https://www.broadcom.com/support/download-search', 'Network / storage'),
    'qualcomm': ('Qualcomm', 'https://www.qualcomm.com/support', 'Wi-Fi / Bluetooth'),
    'epson': ('Epson', 'https://epson.com/Support/sl/s', 'Printer / scanner'),
    'canon': ('Canon', 'https://www.usa.canon.com/support', 'Printer / scanner'),
    'brother': ('Brother', 'https://support.brother.com/', 'Printer / scanner'),
    'logitech': ('Logitech', 'https://support.logi.com/', 'Mouse / keyboard / camera'),
}
DOWNLOAD_HOSTS = {'amd': {'www.amd.com', 'drivers.amd.com'},
                  'intel': {'dsadata.intel.com', 'downloadmirror.intel.com'}}
PUBLISHERS = {'amd': {'Advanced Micro Devices', 'Advanced Micro Devices, Inc.', 'Advanced Micro Devices Inc.'},
              'intel': {'Intel Corporation'}}
MAX_DOWNLOAD = 256 * 1024 * 1024


def trusted_url(vendor, url):
    p = urllib.parse.urlsplit(url)
    if (p.scheme != 'https' or p.hostname not in DOWNLOAD_HOSTS.get(vendor, set())
            or p.username or p.password or p.port not in (None, 443) or p.fragment):
        raise ValueError('Источник загрузки не подтверждён')
    return url


class VendorRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, vendor):
        self.vendor = vendor

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_url(self.vendor, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def vendor_open(vendor, url):
    trusted_url(vendor, url)
    request = urllib.request.Request(url, headers={
        'User-Agent': 'KrolikControl/0.10.4',
        'Referer': SOURCES[vendor][1],
    })
    return urllib.request.build_opener(VendorRedirect(vendor)).open(request, timeout=20)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.extend(v for k, v in attrs if k == 'href' and v)


def amd_installer(page):
    parser = Links()
    parser.feed(page)
    choices = set()
    for link in parser.urls:
        try:
            trusted_url('amd', link)
        except (ValueError, TypeError):
            continue
        p = urllib.parse.urlsplit(link)
        if (p.hostname == 'drivers.amd.com' and not p.query
                and re.fullmatch(r'/drivers/installer/[A-Za-z0-9_./-]+minimalsetup[A-Za-z0-9_.-]*\.exe', p.path, re.I)
                and '..' not in p.path):
            choices.add(link)
    if len(choices) != 1:
        raise ValueError('AMD изменил страницу загрузки. Откройте сайт производителя.')
    return choices.pop()


def recommended_sources(info, devices):
    text = ' '.join(str(info.get(k, '')) for k in ('machine', 'board', 'gpu', 'cpu')).casefold()
    hardware = ''
    for d in devices:
        text += ' ' + ' '.join(str(d.get(k, '')) for k in ('name', 'provider', 'manufacturer')).casefold()
        hardware += ' ' + ' '.join(str(v) for v in d.get('hardware_ids') or []).upper()
    detected = set()
    for token, vendor in {'VEN_1002': 'amd', 'VEN_10DE': 'nvidia', 'VEN_8086': 'intel',
                          'VEN_10EC': 'realtek', 'VEN_14E4': 'broadcom', 'VEN_168C': 'qualcomm',
                          'VEN_17CB': 'qualcomm', 'VID_046D': 'logitech', 'VID_04A9': 'canon',
                          'VID_04B8': 'epson', 'VID_04F9': 'brother', 'VID_03F0': 'hp'}.items():
        if re.search(re.escape(token) + r'(?:[&\\\s]|$)', hardware):
            detected.add(vendor)
    result = []
    for key, (name, url, scope) in SOURCES.items():
        match = name.casefold() in text or (key == 'amd' and ('radeon' in text or 'ryzen' in text))
        if key == 'hp':
            match = bool(re.search(r'\bhp\b|hewlett', text))
        match = match or key in detected
        result.append({'id': key, 'name': name, 'url': url, 'scope': scope,
                       'recommended': match, 'can_download': key in DOWNLOAD_HOSTS})
    return sorted(result, key=lambda r: (not r['recommended'], r['name']))


class DriverSources:
    def __init__(self, app, directory):
        self.app = app
        self.directory = Path(directory) / 'vendor-drivers'
        self.cancel = threading.Event()
        self.ready = {}

    def sources(self):
        return recommended_sources(self.app.info or {}, self.app.data.get('drivers') or [])

    def open_source(self, vendor):
        if vendor not in SOURCES:
            raise ValueError('Неизвестный производитель')
        if not self.app.demo:
            import webbrowser
            webbrowser.open(SOURCES[vendor][1])
        return {'opened': not self.app.demo, 'url': SOURCES[vendor][1]}

    def check_signature(self, path, vendor):
        from .trust import verify
        verify(path)
        row = self.app.backend.psjson(r'''
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$s=Get-AuthenticodeSignature -LiteralPath $p.path
@{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject} | ConvertTo-Json -Compress
''', {'path': str(path)}, timeout=30)
        subject = row.get('subject', '') if isinstance(row, dict) else ''
        # CN may be quoted because company names contain commas.
        match = re.search(r'(?:^|,\s*)CN=(?:"([^"]+)"|([^,]+))', subject)
        cn = next((v for v in match.groups() if v), '') if match else ''
        if not isinstance(row,dict) or row.get('status') != 'Valid' or cn.casefold() not in {v.casefold() for v in PUBLISHERS[vendor]}:
            raise ValueError('Издатель установщика не совпадает с производителем')
        return cn

    def download(self, vendor):
        if vendor not in DOWNLOAD_HOSTS:
            raise ValueError('Для этого производителя доступен официальный сайт')
        if self.app.demo:
            return {'demo': True, 'vendor': vendor, 'message': 'Демо: установщик не скачивался'}
        url = 'https://dsadata.intel.com/installer'
        if vendor == 'amd':
            with vendor_open(vendor, SOURCES[vendor][1]) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Страница производителя слишком большая')
            url = amd_installer(raw.decode('utf-8'))
        ident = secrets.token_hex(16)
        folder = self.directory / ident
        folder.mkdir(parents=True, exist_ok=False)
        if folder.resolve() != folder.absolute() or any(p.is_symlink() for p in (folder, folder.parent)):
            raise ValueError('Папка загрузки является ссылкой')
        target = folder / (vendor + '-setup.exe')
        partial = folder / 'download.part'
        started = time.monotonic()
        try:
            with vendor_open(vendor, url) as response, partial.open('xb') as output:
                trusted_url(vendor, response.geturl())
                declared = response.headers.get('Content-Length')
                if declared is not None and (not declared.isdigit() or not 0 < int(declared) <= MAX_DOWNLOAD):
                    raise ValueError('Недопустимый размер установщика')
                size = 0
                while True:
                    if self.cancel.is_set():
                        raise ValueError('Загрузка отменена')
                    if time.monotonic() - started > 300:
                        raise ValueError('Время загрузки истекло')
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise ValueError('Установщик превышает 256 МиБ')
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size < 1024 or (declared is not None and size != int(declared)):
                raise ValueError('Установщик скачан не полностью')
            with partial.open('rb') as f:
                if f.read(2) != b'MZ':
                    raise ValueError('Производитель вернул страницу вместо установщика')
            # Signature validation also works for PE data with a .part extension.
            publisher = self.check_signature(partial, vendor)
            partial.replace(target)
            with target.open('rb') as f:
                digest = hashlib.file_digest(f,'sha256').hexdigest()
            self.ready[ident] = {'path': target, 'sha256': digest, 'vendor': vendor}
            return {'id': ident, 'vendor': vendor, 'publisher': publisher, 'sha256': digest,
                    'size': size, 'url': url, 'message': 'Установщик скачан. Подпись и издатель проверены.'}
        finally:
            partial.unlink(missing_ok=True)

    def launch(self, body):
        if body.get('confirmed') is not True:
            raise ValueError('Подтвердите запуск установщика производителя')
        job = self.ready.get(body.get('id')) if isinstance(body.get('id'), str) else None
        if not job:
            raise ValueError('Сначала скачайте и проверьте установщик')
        path = job['path']
        if path.is_symlink() or not path.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError('Путь установщика изменился')
        with path.open('rb') as f:
            digest = hashlib.file_digest(f,'sha256').hexdigest()
        if digest != job['sha256']:
            raise ValueError('Файл изменился после загрузки. Скачайте его заново.')
        self.check_signature(path, job['vendor'])
        if not self.app.demo:
            os.startfile(str(path))
        return {'message': 'Открыт установщик производителя. Выберите подходящие обновления в его окне.',
                'verification': 'unverified'}
