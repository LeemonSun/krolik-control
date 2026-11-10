"""Fast read-only registered desktop-app inventory for the curated catalog."""
import re
import hashlib
import unicodedata
from .catalog import APPS

ALIASES={
 'RARLab.WinRAR':['winrar'],
 'Mozilla.Firefox':['mozilla firefox'], 'Google.Chrome':['google chrome'], 'Brave.Brave':['brave'],
 'Opera.Opera':['opera stable','opera'], 'Opera.OperaGX':['opera gx stable','opera gx'],
 'Yandex.Browser':['yandex','yandex browser','яндекс','яндекс браузер'], 'Vivaldi.Vivaldi':['vivaldi'],
 'Microsoft.Edge':['microsoft edge'], 'Valve.Steam':['steam'],
 'EpicGames.EpicGamesLauncher':['epic games launcher'], 'GOG.Galaxy':['gog galaxy'],
 'Ubisoft.Connect':['ubisoft connect','ubisoft game launcher'], '7zip.7zip':['7-zip'],
 'VideoLAN.VLC':['vlc media player'], 'Spotify.Spotify':['spotify'], 'Discord.Discord':['discord'],
 'Telegram.TelegramDesktop':['telegram desktop'], 'Microsoft.VisualStudioCode':['microsoft visual studio code'],
 'Notepad++.Notepad++':['notepad++'], 'OBSProject.OBSStudio':['obs studio'],
 'Microsoft.PowerToys':['powertoys','powertoys (preview)'], 'TheDocumentFoundation.LibreOffice':['libreoffice'],
 'SumatraPDF.SumatraPDF':['sumatrapdf'], 'voidtools.Everything':['everything'],
 'Bitwarden.Bitwarden':['bitwarden'], 'ShareX.ShareX':['sharex'],
}

def normalized(value):
    value=unicodedata.normalize('NFKC',value).casefold().strip()
    value=re.sub(r'\s*\((?:user|system|x64|x86|64-bit|32-bit)\)\s*$','',value)
    return value.strip()

def match_app(name):
    text=normalized(name)
    for ident,names in ALIASES.items():
        if ident not in APPS:continue
        for alias in names:
            if text==alias or re.fullmatch(re.escape(alias)+r'\s+(?:v?\d[\w.+-]*(?:\s|$).*)',text):return ident
    return None

def registered_apps(issues=None):
    import winreg as R
    result=[]
    for hive in (R.HKEY_CURRENT_USER,R.HKEY_LOCAL_MACHINE):
        for view in (R.KEY_WOW64_64KEY,R.KEY_WOW64_32KEY):
            try:
                with R.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\Uninstall',0,R.KEY_READ|view) as root:
                    for i in range(R.QueryInfoKey(root)[0]):
                        try:
                            child=R.EnumKey(root,i)
                            with R.OpenKey(root,child,0,R.KEY_READ|view) as key:
                                name=R.QueryValueEx(key,'DisplayName')[0]
                                try:version=str(R.QueryValueEx(key,'DisplayVersion')[0])[:100]
                                except FileNotFoundError:version=''
                                try:hidden=R.QueryValueEx(key,'SystemComponent')[0]
                                except FileNotFoundError:hidden=0
                                if isinstance(name,str) and not hidden:
                                    def value(field,default=''):
                                        try:return R.QueryValueEx(key,field)[0]
                                        except FileNotFoundError:return default
                                    ident=hashlib.sha256((str(hive)+'|'+str(view)+'|'+child).encode()).hexdigest()
                                    result.append({'record_id':ident,'name':name[:512],'version':version,'publisher':str(value('Publisher'))[:300],'scope':'user' if hive==R.HKEY_CURRENT_USER else 'machine','architecture':'x64' if view==R.KEY_WOW64_64KEY else 'x86','source':'registry','registry_hive':'HKCU' if hive==R.HKEY_CURRENT_USER else 'HKLM','registry_view':'x64' if view==R.KEY_WOW64_64KEY else 'x86','architecture_source':'registry_view','registry_key':child,'uninstall':str(value('UninstallString'))[:32768],'quiet_uninstall':str(value('QuietUninstallString'))[:32768],'modify':str(value('ModifyPath'))[:32768],'location':str(value('InstallLocation'))[:4096],'size_kb':value('EstimatedSize',None) if type(value('EstimatedSize',None))==int and value('EstimatedSize',None)>=0 else None,'windows_installer':value('WindowsInstaller',0)==1,'no_remove':bool(value('NoRemove',0)),'no_repair':bool(value('NoRepair',0))})
                        except PermissionError:
                            if issues is not None and 'Часть записей установленных программ недоступна' not in issues:issues.append('Часть записей установленных программ недоступна')
                        except FileNotFoundError:continue
            except PermissionError:
                if issues is not None and 'Часть записей установленных программ недоступна' not in issues:issues.append('Часть записей установленных программ недоступна')
            except FileNotFoundError:continue
    return collapse_shared_user_views(result)

def collapse_shared_user_views(rows):
    result=[];seen={}
    for row in rows:
        if row.get('registry_hive')!='HKCU':result.append(row);continue
        key=row.get('registry_key');signature={k:v for k,v in row.items() if k not in ('record_id','architecture','registry_view','architecture_source')}
        prior=seen.get(key)
        if prior and prior[1]==signature:
            prior[0].update(architecture=None,architecture_source='shared_registry',registry_view='shared',record_id=hashlib.sha256(('HKCU|shared|'+key).encode()).hexdigest());continue
        copy=dict(row);seen[key]=(copy,signature);result.append(copy)
    return result

def local_inventory(entries=None):
    installed={}
    for row in (registered_apps() if entries is None else entries):
        ident=match_app(row['name'])
        if ident:
            v={'version':row.get('version',''),'record_id':row.get('record_id'),'architecture':row.get('architecture'),'scope':row.get('scope')}
            if v not in installed.setdefault(ident,[]):installed[ident].append(v)
    result=[]
    for ident in APPS:
        installs=sorted(installed.get(ident,[]),key=lambda r:(r.get('architecture') or '',r.get('scope') or '',r['version']))
        versions=sorted(set(r['version'] for r in installs if r['version']))
        result.append({'id':ident,'installed':bool(installs),'version':' / '.join(versions),'installations':installs,'multiple_installations':len(installs)>1,'available_version':None,'update_available':False,'update_check':'not_checked'})
    return result
