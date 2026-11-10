"""Verified Microsoft package-manager bootstrap and allowlisted app operations."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from .catalog import APPS

RELEASE_API='https://api.github.com/repos/microsoft/winget-cli/releases/latest'
BUNDLE='Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle'
DEPENDENCIES='DesktopAppInstaller_Dependencies.zip'
PUBLISHER='CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US'
DOWNLOAD_HOSTS={'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com','objects-origin.githubusercontent.com'}
MAX_ASSET=512*1024*1024

class PackageError(RuntimeError):
    def __init__(self,message,*,details='',code=None):
        super().__init__(message);self.details=str(details)[-6000:];self.code=code
class SetupError(PackageError):pass
class UserCancelled(PackageError):pass
class ProcessError(RuntimeError):
    def __init__(self,code,stdout='',stderr=''):
        self.code=int(code)&0xffffffff;self.stdout=stdout;self.stderr=stderr
        super().__init__((stderr or stdout or f'Код 0x{self.code:08X}')[-1600:])


def safe_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or p.hostname not in DOWNLOAD_HOSTS or p.username or p.password or p.port not in (None,443):raise SetupError('Не удалось проверить источник загрузки.')
    return url

class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        safe_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def open_official(url):
    safe_url(url)
    request=urllib.request.Request(url,headers={'User-Agent':'KrolikControl','Accept':'application/vnd.github+json' if url==RELEASE_API else 'application/octet-stream'})
    return urllib.request.build_opener(TrustedRedirect()).open(request,timeout=25)


def release_assets(raw):
    if not isinstance(raw,dict) or raw.get('draft') is not False or raw.get('prerelease') is not False:raise SetupError('Официальный стабильный пакет пока недоступен.')
    tag=raw.get('tag_name','')
    if not isinstance(tag,str) or not re.fullmatch(r'v?\d+(?:\.\d+){1,4}',tag):raise SetupError('Не удалось проверить версию компонента.')
    assets=raw.get('assets')
    if not isinstance(assets,list) or len(assets)>200:raise SetupError('Не удалось получить список официальных файлов.')
    result={}
    for name in (BUNDLE,DEPENDENCIES):
        matches=[a for a in assets if isinstance(a,dict) and a.get('name')==name]
        if len(matches)!=1:raise SetupError('Официальный пакет неполный. Повторите позже.')
        a=matches[0];url=a.get('browser_download_url','');digest=a.get('digest','');size=a.get('size')
        if not isinstance(digest,str) or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest):raise SetupError('Для официального файла нет контрольной суммы. Установка остановлена.')
        if type(size)!=int or not 0<size<=MAX_ASSET:raise SetupError('Недопустимый размер официального файла.')
        if url!=f'https://github.com/microsoft/winget-cli/releases/download/{tag}/{name}':raise SetupError('Источник пакета не совпал с официальным выпуском.')
        result[name]={'url':url,'size':size,'sha256':digest[7:].lower()}
    return result


def download_verified(asset,destination,progress,cancel=None,opener=None):
    opener=opener or open_official
    path=Path(destination);partial=path.with_suffix(path.suffix+'.part');count=0;digest=hashlib.sha256();started=time.monotonic();last=-1
    try:
        with opener(asset['url']) as response,partial.open('xb') as file:
            while True:
                if cancel is not None and cancel.is_set():raise UserCancelled('Подготовка остановлена.')
                if time.monotonic()-started>900:raise SetupError('Загрузка заняла слишком много времени. Проверьте интернет и повторите.')
                block=response.read(256*1024)
                if not block:break
                count+=len(block)
                if count>asset['size'] or count>MAX_ASSET:raise SetupError('Размер загрузки не совпал с официальным файлом.')
                file.write(block);digest.update(block)
                percent=int(count*100/asset['size'])
                if percent!=last:progress(f'Подготовка установки · загрузка {percent}%');last=percent
            file.flush();os.fsync(file.fileno())
        if count!=asset['size'] or digest.hexdigest()!=asset['sha256']:raise SetupError('Загруженный файл не прошёл проверку. Повторите загрузку.')
        partial.replace(path);return path
    finally:partial.unlink(missing_ok=True)


def _manifest_identity(package,bundle=False):
    name='AppxMetadata/AppxBundleManifest.xml' if bundle else 'AppxManifest.xml'
    with zipfile.ZipFile(package) as archive:
        info=archive.getinfo(name)
        if info.file_size>262144:raise SetupError('Манифест компонента повреждён.')
        root=ET.fromstring(archive.read(info))
    identity=next((e for e in root if e.tag.rsplit('}',1)[-1]=='Identity'),None)
    if identity is None or identity.get('Publisher')!=PUBLISHER:raise SetupError('Издатель компонента не совпал с Microsoft.')
    return identity.attrib


def verify_bundle(path):
    if _manifest_identity(path,bundle=True).get('Name')!='Microsoft.DesktopAppInstaller':raise SetupError('Загружен другой компонент. Установка остановлена.')


def unpack_dependencies(path,destination,architecture='x64'):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);result=[];expanded=0
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if len(entries)>512:raise SetupError('Архив компонентов повреждён.')
        for entry in entries:
            member=PurePosixPath(entry.filename.replace('\\','/'))
            if member.is_absolute() or '..' in member.parts or ':' in entry.filename:raise SetupError('Архив содержит недопустимый путь.')
            if member.suffix.lower() not in ('.appx','.msix'):continue
            if any(a in member.parts for a in ('x86','x64','arm','arm64') if a!=architecture):continue
            expanded+=entry.file_size
            if entry.file_size>128*1024*1024 or expanded>384*1024*1024:raise SetupError('Архив компонентов слишком большой.')
            target=destination/f'dependency-{len(result)}{member.suffix.lower()}'
            with archive.open(entry) as source,target.open('xb') as out:shutil.copyfileobj(source,out,256*1024)
            identity=_manifest_identity(target)
            if identity.get('ProcessorArchitecture') not in (architecture,'neutral'):target.unlink();continue
            if not re.fullmatch(r'Microsoft\.(?:VCLibs\.[\d.]+(?:\.UWPDesktop)?|UI\.Xaml\.[\d.]+|WindowsAppRuntime\.[\d.]+)',identity.get('Name','')):raise SetupError('В архиве обнаружен неожиданный компонент.')
            result.append(str(target))
    if not result:raise SetupError('В официальном пакете нет компонентов для этой Windows.')
    return result


def user_error(exc,action='install'):
    if isinstance(exc,PackageError):return exc
    code=getattr(exc,'code',None)
    if code is not None:code=int(code)&0xffffffff
    messages={
        0x800704c7:'Установка отменена в окне Windows.',0x8a15010c:'Установка отменена.',0x8a150005:'Установка остановлена.',
        0x80070005:'Windows не разрешила установку. Подтвердите запрос прав и повторите.',
        0x8a15000f:'Каталог установки ещё не загружен. Проверьте интернет и повторите.',
        0x8a150014:'Программа не найдена в каталоге. Обновите список и повторите.',0x8a150016:'В каталоге найдено несколько пакетов. Повторите проверку.',
        0x8a15002b:'Для этой программы нет подходящего обновления.',
        0x8a150011:'Файл программы не прошёл проверку. Повторите загрузку.',0x8a150010:'Для этой Windows нет подходящей версии программы.',
        0x8a150101:'Закройте программу и повторите установку.',0x8a150103:'Файлы программы используются. Закройте её и повторите.',
        0x8a150102:'Windows уже выполняет другую установку. Дождитесь её завершения.',0x8a150105:'Недостаточно места на диске. Освободите место и повторите.',
        0x8a150107:'Для установки нужен интернет. Проверьте подключение.',0x8a15003a:'Установка запрещена настройками организации.',0x8a15010f:'Установка запрещена настройками организации.',
        0x8a150019:'Подтвердите запрос прав администратора для установки.',0x8a15010a:'Перезагрузите Windows, затем повторите установку.',
        0x8a150068:'Обновление этой программы закреплено или запрещено её настройками.',
        0x80072ee7:'Не удалось найти сервер загрузки. Проверьте интернет и DNS.',
        0x80072efd:'Нет соединения с сервером загрузки. Проверьте интернет.',
        0x80072ee2:'Сервер не ответил вовремя. Повторите позже.',
    }
    message=messages.get(code)
    if isinstance(exc,(urllib.error.URLError,TimeoutError,ConnectionError)):message='Не удалось загрузить файл. Проверьте интернет и повторите.'
    if message is None:message='Не удалось обновить программу. Откройте подробности или повторите.' if action=='upgrade' else 'Не удалось установить программу. Откройте подробности или повторите.'
    return PackageError(message,details=str(exc),code=code)

class PackageManager:
    def __init__(self,backend):self.backend=backend;self.path=None;self.ready_state=None
    def candidate(self):
        return self.path if self.path and Path(self.path).is_file() else shutil.which('winget.exe')
    def available_hint(self):return self.ready_state if self.ready_state is not None else bool(self.candidate())
    def _probe(self,path):
        if not path:return False
        try:return bool(re.fullmatch(r'v?\d+(?:\.\d+){1,4}',self.backend.run([path,'--version'],timeout=25).strip()))
        except (OSError,RuntimeError,TimeoutError,subprocess.TimeoutExpired):return False
    def _registered(self,repair=False):
        try:
            result=self.backend.psjson(r"""
$package=Get-AppxPackage -Name Microsoft.DesktopAppInstaller | Sort-Object Version -Descending | Select-Object -First 1
if($package -and $package.Publisher -eq $p.publisher){
 if($p.repair){$manifest=Join-Path $package.InstallLocation 'AppxManifest.xml';Add-AppxPackage -Register $manifest -DisableDevelopmentMode -ErrorAction Stop}
 $candidate=Join-Path $package.InstallLocation 'winget.exe';if(Test-Path -LiteralPath $candidate){@{path=$candidate}|ConvertTo-Json -Compress}
}
""",{'publisher':PUBLISHER,'repair':repair},timeout=90)
            candidate=result.get('path') if isinstance(result,dict) else None
            if isinstance(candidate,str) and Path(candidate).is_file() and self._probe(candidate):self.path=candidate;self.ready_state=True;return candidate
        except (OSError,RuntimeError,ValueError,TimeoutError,subprocess.TimeoutExpired):pass
        return None
    def resolve(self):
        candidate=self.candidate()
        if self._probe(candidate):self.path=candidate;self.ready_state=True;return candidate
        found=self._registered();self.ready_state=bool(found);return found
    def prepare(self,progress=lambda s:None,cancel=None):
        try:
            progress('Проверяем возможность установки программ')
            candidate=self.resolve()
            if candidate:return {'ready':True,'message':'Установка программ готова'}
            if cancel is not None and cancel.is_set():raise UserCancelled('Подготовка остановлена.')
            progress('Подготавливаем встроенный компонент Microsoft')
            if self._registered(repair=True):return {'ready':True,'message':'Установка программ готова'}
            with open_official(RELEASE_API) as response:
                raw=response.read(2*1024*1024+1)
                if len(raw)>2*1024*1024:raise SetupError('Ответ официального каталога слишком большой.')
                assets=release_assets(json.loads(raw))
            with tempfile.TemporaryDirectory(prefix='KrolikControl-Setup-') as directory:
                root=Path(directory);bundle=download_verified(assets[BUNDLE],root/BUNDLE,progress,cancel);verify_bundle(bundle)
                dependencies=download_verified(assets[DEPENDENCIES],root/DEPENDENCIES,progress,cancel)
                paths=unpack_dependencies(dependencies,root/'dependencies')
                if cancel is not None and cancel.is_set():raise UserCancelled('Подготовка остановлена.')
                progress('Windows проверяет и устанавливает компонент Microsoft')
                # Windows deployment validates the package signature. No policy/certificate bypass.
                self.backend.ps("Add-AppxPackage -Path $p.bundle -DependencyPath $p.dependencies -ErrorAction Stop",{'bundle':str(bundle),'dependencies':paths},timeout=600)
            if not self._registered() and not self.resolve():raise SetupError('Компонент установлен, но Windows ещё не разрешила его запуск. Повторите подготовку.')
            return {'ready':True,'message':'Можно устанавливать программы'}
        except UserCancelled:raise
        except Exception as exc:
            if isinstance(exc,SetupError):raise
            raise SetupError('Не удалось подготовить установку программ. Проверьте интернет и повторите.',details=str(exc)) from exc
    def ready(self):
        return self.prepare(getattr(self.backend,'progress',lambda s:None),getattr(self.backend,'cancel_event',None))
    def _command(self,args,timeout=1500):
        path=self.path or self.resolve()
        if not path:raise SetupError('Установка программ не готова. Повторите подготовку.')
        return self.backend.run([path,*args],timeout=timeout)
    def preflight(self):
        cancel=getattr(self.backend,'cancel_event',None)
        if cancel is not None and cancel.is_set():raise UserCancelled('Установка остановлена до запуска установщика.')
        if os.name=='nt':
            root=Path(os.environ.get('SystemRoot',r'C:\Windows')).anchor
            if shutil.disk_usage(root).free<256*1024**2:raise PackageError('На системном диске меньше 256 МиБ. Освободите место перед установкой.')
    def install(self,ident):
        if ident not in APPS:raise ValueError('Программа отсутствует в каталоге')
        self.preflight();self.ready();self.preflight()
        try:
            self._command(['list','--id',ident,'--exact','--source','winget','--accept-source-agreements','--disable-interactivity'],timeout=120)
            return {'installed':True,'message':'Уже установлена'}
        except ProcessError as exc:
            # APPINSTALLER_CLI_ERROR_NO_APPLICATIONS_FOUND is the only absence result.
            if exc.code!=0x8a150014:raise user_error(exc)
        self.backend.progress('Загрузка и установка · '+APPS[ident][0]) if callable(getattr(self.backend,'progress',None)) else None
        try:
            self._command(['install','--id',ident,'--exact','--source','winget','--silent','--disable-interactivity','--no-upgrade','--accept-package-agreements','--accept-source-agreements'])
        except ProcessError as exc:
            if exc.code in (3010,0x8a150109):return {'installed':True,'reboot':True,'message':'Установлено. Нужна перезагрузка Windows'}
            raise user_error(exc)
        try:self._command(['list','--id',ident,'--exact','--source','winget','--accept-source-agreements','--disable-interactivity'],timeout=120)
        except Exception as exc:raise PackageError('Установщик завершился, но программа пока не найдена в Windows. Повторите проверку.',details=str(exc)) from exc
        return {'installed':True,'message':'Программа установлена и найдена в Windows'}
    def upgrade(self,ident):
        if ident not in APPS:raise ValueError('Программа отсутствует в каталоге')
        self.preflight();self.ready();self.preflight()
        try:self._command(['upgrade','--id',ident,'--exact','--source','winget','--silent','--disable-interactivity','--accept-package-agreements','--accept-source-agreements'])
        except ProcessError as exc:
            if exc.code==0x8a15002b:return {'installed':True,'message':'Подходящее обновление не предложено'}
            if exc.code in (3010,0x8a150109):return {'installed':True,'reboot':True,'message':'Обновлено. Нужна перезагрузка Windows'}
            raise user_error(exc,'upgrade')
        return {'installed':True,'message':'Обновление завершено'}
