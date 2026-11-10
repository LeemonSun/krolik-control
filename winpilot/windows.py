"""Windows inventory and allowlisted settings backend; no shell=True."""
import base64
import ctypes
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from . import native
from .packages import PackageManager, ProcessError, user_error

GUID=re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}')
REG = {
 'clipboard_history':[(r'Software\Microsoft\Clipboard','EnableClipboardHistory',{'on':1,'off':0})],
 'toast_notifications':[(r'Software\Microsoft\Windows\CurrentVersion\PushNotifications','ToastEnabled',{'on':1,'off':0})],
 'printscreen_snipping':[(r'Control Panel\Keyboard','PrintScreenKeyForSnippingEnabled',{'on':1,'off':0})],
 'nav_expand':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','NavPaneExpandToCurrentFolder',{'on':1,'off':0})],
 'file_checkboxes':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','AutoCheckSelect',{'on':1,'off':0})],
 'compact_explorer':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','UseCompactMode',{'on':1,'off':0})],
 'taskbar_badges':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','TaskbarBadges',{'on':1,'off':0})],
 'theme': [('Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize','AppsUseLightTheme',{'dark':0,'light':1}),('Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize','SystemUsesLightTheme',{'dark':0,'light':1})],
 'transparency':[('Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize','EnableTransparency',{'on':1,'off':0})],
 'extensions':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','HideFileExt',{'on':0,'off':1})],
 'hidden':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','Hidden',{'on':1,'off':2})],
 'explorer_home':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','LaunchTo',{'pc':1,'home':2})],
 'taskbar_align':[('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced','TaskbarAl',{'left':0,'center':1})],
 'switch_keys':[('Keyboard Layout\\Toggle','Hotkey',{'1':'1','2':'2','3':'3'}),('Keyboard Layout\\Toggle','Language Hotkey',{'1':'1','2':'2','3':'3'}),('Keyboard Layout\\Toggle','Layout Hotkey',{'1':'1','2':'2','3':'3'})],
 'game_mode':[('Software\\Microsoft\\GameBar','AutoGameModeEnabled',{'on':1,'off':0})],
 'game_capture':[('Software\\Microsoft\\Windows\\CurrentVersion\\GameDVR','AppCaptureEnabled',{'on':1,'off':0}),('System\\GameConfigStore','GameDVR_Enabled',{'on':1,'off':0})],
 'ads':[('Software\\Microsoft\\Windows\\CurrentVersion\\AdvertisingInfo','Enabled',{'on':1,'off':0})],
 'suggestions': [('Software\\Microsoft\\Windows\\CurrentVersion\\ContentDeliveryManager',k,{'on':1,'off':0}) for k in ['SubscribedContent-338388Enabled','SubscribedContent-338389Enabled','SubscribedContent-353694Enabled','SubscribedContent-353696Enabled','SystemPaneSuggestionsEnabled']],
 'personalization':[('Software\\Microsoft\\Windows\\CurrentVersion\\Privacy','TailoredExperiencesWithDiagnosticDataEnabled',{'on':1,'off':0})],
}
CREATE_NO_WINDOW=0x08000000 if os.name=='nt' else 0

class Windows:
    def __init__(self):
        self.display_guard=native.DisplayGuard();self.process_lock=threading.Lock();self.processes=set();self.package_manager=PackageManager(self);self.progress=lambda text:None;self.cancel_event=None
    def is_admin(self):
        return bool(os.name=='nt' and ctypes.windll.shell32.IsUserAnAdmin())
    def run(self,args,timeout=60):
        p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=CREATE_NO_WINDOW)
        with self.process_lock:self.processes.add(p)
        try:
            try:stdout,stderr=p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill();p.communicate();raise
        finally:
            with self.process_lock:self.processes.discard(p)
        encoding='utf-8'
        if os.name=='nt' and Path(args[0]).name.lower() in ('powercfg.exe','pnputil.exe'):
            encoding=f'cp{ctypes.windll.kernel32.GetOEMCP()}'
        text=stdout.decode(encoding,errors='replace').strip()
        if p.returncode:
            raise ProcessError(p.returncode,text,stderr.decode(encoding,errors='replace').strip())
        return text
    def stop_processes(self):
        with self.process_lock:processes=list(self.processes)
        for process in processes:
            try:process.kill()
            except OSError:pass
    def ps(self,script,data=None,timeout=40):
        payload=base64.b64encode(json.dumps(data or {},ensure_ascii=False).encode()).decode()
        prefix="$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        prefix+=f"$p=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json);\n"
        script=prefix+script
        # File avoids Windows' 32767-character command-line limit on driver inventory.
        fd,name=tempfile.mkstemp(suffix='.ps1')
        try:
            with os.fdopen(fd,'w',encoding='utf-8-sig') as f: f.write(script)
            return self.run([str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe') if os.name=='nt' else 'powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',name],timeout)
        finally:
            Path(name).unlink(missing_ok=True)
    def psjson(self,script,data=None,timeout=40):
        raw=self.ps(script,data,timeout)
        return json.loads(raw) if raw else None
    def quick_inventory(self):
        """No PowerShell/CIM: publish screens and input before slow system metadata."""
        import sys
        import winreg as R
        class MEMORY(ctypes.Structure):
            _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[(k,ctypes.c_uint64) for k in ['total','avail','page','availpage','virtual','availvirtual','extended']]
        class POWER(ctypes.Structure):
            _fields_=[('ac',ctypes.c_ubyte),('flag',ctypes.c_ubyte),('percent',ctypes.c_ubyte),('saving',ctypes.c_ubyte),('life',ctypes.c_uint32),('full',ctypes.c_uint32)]
        memory=MEMORY();memory.length=ctypes.sizeof(memory)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
        power=POWER();power_ok=ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power))
        cpu=os.environ.get('PROCESSOR_IDENTIFIER','Процессор')
        try:
            with R.OpenKey(R.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as h:cpu=R.QueryValueEx(h,'ProcessorNameString')[0].strip()
        except OSError:pass
        devices=self.device_inventory()
        settings=self.read_settings();settings.update(native.read_input())
        return dict(privileged_helper=True,hostname=os.environ.get('COMPUTERNAME','Windows PC'),os='Windows 11' if sys.getwindowsversion().build>=22000 else 'Windows 10',build=str(sys.getwindowsversion().build),cpu=[cpu],gpu=list(dict.fromkeys(d['gpu'] for d in devices['displays'])),ram=round(memory.total/1024**3,1),machine='',admin=self.is_admin(),winget=self.package_manager.available_hint(),battery=bool(power_ok and power.flag!=255 and not power.flag&128),network=[],languages=[],audio=[],startup=[],power_plans=[],board=None,bios=None,disks=[],brightness=[],settings=settings,pending_groups=['power','network','language'],**devices)
    def device_inventory(self):
        devices={'displays':native.enumerate_displays()}
        try:
            from .audio import enumerate_audio
            devices['endpoints']=enumerate_audio();devices['audio_error']=''
        except Exception as exc:devices['endpoints']=[];devices['audio_error']=str(exc)
        return devices
    def inventory(self):
        info=self.quick_inventory();details=self.inventory_details()
        info['settings'].update(details.pop('settings',{}));info.update(details)
        return info
    def inventory_details(self):
        info=self.psjson(r'''
$net=@(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
 $a=$_; $dns=Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
 @{id=[int]$a.ifIndex; guid=[string]$a.InterfaceGuid; name=$a.Name; description=$a.InterfaceDescription; status=[string]$a.Status; dns=@($dns.ServerAddresses)}
})
$lang=@(Get-WinUserLanguageList | ForEach-Object {$_.LanguageTag})
$brightness=@(Get-CimInstance -Namespace root/wmi -Class WmiMonitorBrightness -ErrorAction SilentlyContinue | ForEach-Object {@{id=$_.InstanceName; value=[int]$_.CurrentBrightness}})
@{time_zones=@([TimeZoneInfo]::GetSystemTimeZones()|ForEach-Object{@{id=$_.Id;name=$_.DisplayName}});time_zone=[TimeZoneInfo]::Local.Id;network=$net; languages=$lang; brightness=$brightness; language_options=@([Globalization.CultureInfo]::GetCultures('SpecificCultures') | ForEach-Object {@{id=$_.Name;name=$_.DisplayName}})} | ConvertTo-Json -Depth 6 -Compress
''',timeout=35)
        info['settings']={}
        if info.get('time_zone'):info['settings']['time_zone']=info['time_zone']
        layouts={'ru-RU,en-US':'ru-en','en-US,ru-RU':'en-ru','ru-RU':'ru','en-US':'en'}
        base_langs=[v for v in info['languages'] if v in ('ru-RU','en-US')]
        if ','.join(base_langs) in layouts: info['settings']['layouts']=layouts[','.join(base_langs)]
        plans=self.run(['powercfg.exe','/list'])
        info['power_plans']=[]
        for line in plans.splitlines():
            m=GUID.search(line)
            if m:
                name=line[m.end():].strip().strip('*').strip().strip('()')
                info['power_plans'].append({'id':m.group().lower(),'name':name})
                if '*' in line: info['settings']['power_plan']=m.group().lower()
        # Localized powercfg text still has universal hex AC/DC indices.
        for subgroup,key,prefix in [('SUB_VIDEO','VIDEOIDLE','screen'),('SUB_SLEEP','STANDBYIDLE','sleep')]:
            try:
                raw=self.run(['powercfg.exe','/query','SCHEME_CURRENT',subgroup,key])
                vals=re.findall(r'0x([0-9a-fA-F]{8})',raw)
                if len(vals)>=2:
                    info['settings'][prefix+'_ac']=str(int(vals[-2],16)//60)
                    info['settings'][prefix+'_dc']=str(int(vals[-1],16)//60)
            except Exception: pass
        info['pending_groups']=[]
        return info
    def drivers(self):
        result=self.psjson(r'''
$map=@{}; Get-CimInstance Win32_PnPSignedDriver | ForEach-Object {$map[$_.DeviceID]=$_}
@(Get-CimInstance Win32_PnPEntity | ForEach-Object {
 $d=$map[$_.DeviceID]
 @{id=$_.DeviceID; name=$_.Name; category=$_.PNPClass; status=$_.Status; problem=[int]$_.ConfigManagerErrorCode; provider=$d.DriverProviderName; version=$d.DriverVersion; date=if($d.DriverDate){$d.DriverDate.ToString('yyyy-MM-dd')}else{''}; inf=$d.InfName; hardware_ids=@($_.HardwareID); compatible_ids=@($_.CompatibleID)}
}) | ConvertTo-Json -Depth 4 -Compress
''',timeout=90) or []
        return result if isinstance(result,list) else [result]
    def search_updates(self,kind):
        if kind not in ('Driver','Software'): raise ValueError('Invalid update type')
        result=self.psjson(r'''
$s=New-Object -ComObject Microsoft.Update.Session
$q=$s.CreateUpdateSearcher()
$r=$q.Search("IsInstalled=0 and IsHidden=0 and Type='$($p.kind)'")
@($r.Updates | ForEach-Object {@{id=$_.Identity.UpdateID; revision=$_.Identity.RevisionNumber; name=$_.Title; downloaded=$_.IsDownloaded; size=[math]::Round($_.MaxDownloadSize/1MB,1); driver=($_.Type -eq 2); hardware_id=if($_.Type -eq 2){[string]$_.DriverHardwareID}else{''}; category=if($_.Type -eq 2){[string]$_.DriverClass}else{''}; provider=if($_.Type -eq 2){[string]$_.DriverManufacturer}else{''}}}) | ConvertTo-Json -Depth 4 -Compress
''',{'kind':kind},timeout=900) or []
        return result if isinstance(result,list) else [result]
    def install_update(self,ident,revision):
        if not self.is_admin():
            from .privilege import request
            return request(self,'update',{'id':ident,'revision':revision})
        return self.psjson(r'''
$s=New-Object -ComObject Microsoft.Update.Session
$r=$s.CreateUpdateSearcher().Search("UpdateID='$($p.id)' and RevisionNumber=$($p.revision)")
if($r.Updates.Count -ne 1){throw 'Обновление больше не доступно. Повторите поиск.'}
$u=$r.Updates.Item(0)
if($u.IsInstalled){@{reboot=$false; message='Уже установлено'}|ConvertTo-Json -Compress; exit}
if(-not $u.EulaAccepted){$u.AcceptEula()}
$c=New-Object -ComObject Microsoft.Update.UpdateColl; [void]$c.Add($u)
$d=$s.CreateUpdateDownloader(); $d.Updates=$c; $download=$d.Download()
if($download.ResultCode -ne 2){throw "Загрузка не завершена: $($download.ResultCode)"}
$i=$s.CreateUpdateInstaller(); $i.Updates=$c; $v=$i.Install()
$one=$v.GetUpdateResult(0)
if($one.ResultCode -ne 2){throw "Ошибка установки: $($one.ResultCode), HRESULT $($one.HResult)"}
@{reboot=$v.RebootRequired; message='Установлено'} | ConvertTo-Json -Compress
''',{'id':ident,'revision':revision},timeout=1800)
    def read_settings(self):
        import winreg as R
        result={}
        for key,items in REG.items():
            values=[]
            for path,name,choices in items:
                try:
                    with R.OpenKey(R.HKEY_CURRENT_USER,path) as h: value,_=R.QueryValueEx(h,name)
                    values.append(next((k for k,v in choices.items() if value==v),None))
                except OSError: values.append(None)
            if values and values[0] is not None and len(set(values))==1: result[key]=values[0]
        return result
    def reg_snapshot(self,key):
        import winreg as R
        values=[]
        for path,name,_ in REG[key]:
            try:
                with R.OpenKey(R.HKEY_CURRENT_USER,path) as h: value,kind=R.QueryValueEx(h,name)
                values.append({'path':path,'name':name,'value':value,'kind':kind,'exists':True})
            except FileNotFoundError: values.append({'path':path,'name':name,'exists':False})
        return values
    def set_registry(self,key,value):
        import winreg as R
        for path,name,choices in REG[key]:
            v=choices[value]
            with R.CreateKeyEx(R.HKEY_CURRENT_USER,path,0,R.KEY_SET_VALUE) as h:
                R.SetValueEx(h,name,0,R.REG_SZ if isinstance(v,str) else R.REG_DWORD,v)
        if key=='switch_keys':
            if not native.user32().SystemParametersInfoW(0x5B,0,None,3):raise ctypes.WinError(ctypes.get_last_error())
        self.broadcast()
    def restore_registry(self,values):
        import winreg as R
        allowed={(p,n) for items in REG.values() for p,n,_ in items}
        for v in values:
            if (v['path'],v['name']) not in allowed: raise ValueError('Недопустимый ключ отката')
            with R.CreateKeyEx(R.HKEY_CURRENT_USER,v['path'],0,R.KEY_SET_VALUE) as h:
                if v['exists']: R.SetValueEx(h,v['name'],0,v['kind'],v['value'])
                else:
                    try: R.DeleteValue(h,v['name'])
                    except FileNotFoundError: pass
        if any(v['path']==r'Keyboard Layout\Toggle' for v in values):
            if not native.user32().SystemParametersInfoW(0x5B,0,None,3):raise ctypes.WinError(ctypes.get_last_error())
        self.broadcast()
    def broadcast(self):
        u=ctypes.WinDLL('user32',use_last_error=True)
        u.SendMessageTimeoutW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_size_t)]
        result=ctypes.c_size_t()
        u.SendMessageTimeoutW(0xffff,0x1a,0,'ImmersiveColorSet',2,1000,ctypes.byref(result))
    def apply_setting(self,key,value,adapter=None):
        if key in ('dns','time_zone') and not self.is_admin():
            from .privilege import request
            if key=='time_zone':return request(self,key,value)
            guid=self.psjson('[string](Get-NetAdapter -InterfaceIndex $p.id -ErrorAction Stop).InterfaceGuid | ConvertTo-Json -Compress',{'id':adapter})
            return request(self,'dns',{'adapter':adapter,'guid':str(guid).strip('{}'),'choice':value})
        if key in REG: self.set_registry(key,value); return
        if key in native.NATIVE_KEYS: native.set_input(key,value); return
        if key=='time_zone':
            self.ps('Set-TimeZone -Id $p.id -ErrorAction Stop',{'id':value});return
        if key=='layouts':
            langs={'ru-en':['ru-RU','en-US'],'en-ru':['en-US','ru-RU'],'ru':['ru-RU'],'en':['en-US']}[value]
            self.ps("$old=Get-WinUserLanguageList; $l=New-WinUserLanguageList $p.langs[0];$l.Clear();foreach($tag in $p.langs){$entry=@($old | Where-Object LanguageTag -eq $tag);if($entry.Count){$l.Add($entry[0])}else{$l.Add((New-WinUserLanguageList $tag)[0])}};foreach($entry in $old){if($entry.LanguageTag -notin @('ru-RU','en-US')){$l.Add($entry)}};Set-WinUserLanguageList $l -Force;if($l[0].InputMethodTips.Count){Set-WinDefaultInputMethodOverride -InputTip $l[0].InputMethodTips[0]}",{'langs':langs}); return
        if key=='power_plan': self.run(['powercfg.exe','/setactive',value]); return
        if key in ['screen_ac','sleep_ac','screen_dc','sleep_dc']:
            option={'screen_ac':'monitor-timeout-ac','sleep_ac':'standby-timeout-ac','screen_dc':'monitor-timeout-dc','sleep_dc':'standby-timeout-dc'}[key]
            self.run(['powercfg.exe','/change',option,value]); return
        if key=='dns':
            self.ps("if($p.value -eq 'auto'){Get-DnsClientServerAddress -InterfaceIndex $p.adapter -AddressFamily IPv4 | Set-DnsClientServerAddress -ResetServerAddresses}else{Set-DnsClientServerAddress -InterfaceIndex $p.adapter -ServerAddresses $p.servers}",{'adapter':int(adapter),'value':value,'servers':{'auto':[],'cloudflare':['1.1.1.1','1.0.0.1'],'google':['8.8.8.8','8.8.4.4']}[value]}); return
        raise ValueError('Неизвестная настройка')
    def get_brightness(self,ident):
        value=self.psjson("$m=Get-CimInstance -Namespace root/wmi -Class WmiMonitorBrightness | Where-Object InstanceName -eq $p.id; if(-not $m){throw 'Экран отключён'}; [int]$m.CurrentBrightness | ConvertTo-Json",{'id':ident})
        return int(value)
    def brightness(self,ident,value):
        self.ps("$m=Get-CimInstance -Namespace root/wmi -Class WmiMonitorBrightnessMethods | Where-Object InstanceName -eq $p.id; if(-not $m){throw 'Регулировка недоступна'}; $r=Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{Timeout=[uint32]1; Brightness=[byte]$p.value}; if($r.ReturnValue -ne 0){throw 'Монитор отклонил яркость'}",{'id':ident,'value':value})
    def prepare_package_manager(self):
        return self.package_manager.ready()
    def install_app(self,ident):
        try:return self.package_manager.install(ident)
        except Exception as exc:raise user_error(exc) from exc
    def restore_point(self):
        if not self.is_admin():
            from .privilege import request
            return request(self,'restore_point',{})
        return self.psjson("$before=@(Get-ComputerRestorePoint | ForEach-Object {$_.SequenceNumber}); Checkpoint-Computer -Description 'Krolik Control before changes' -RestorePointType MODIFY_SETTINGS; $new=@(Get-ComputerRestorePoint | Where-Object {$_.Description -eq 'Krolik Control before changes' -and $_.SequenceNumber -notin $before}); if($new.Count -eq 0){throw 'Windows не создала новую точку восстановления. Проверьте защиту системы и ограничение частоты создания точек.'};[int]($new|Select-Object -Last 1).SequenceNumber|ConvertTo-Json -Compress",timeout=120)
    def restore_dns(self,value):
        if not self.is_admin():
            from .privilege import request
            return request(self,'dns_restore',value)
        self.ps("$a=Get-NetAdapter -InterfaceIndex $p.adapter; if($p.value.guid -and ([guid]$a.InterfaceGuid) -ne ([guid]$p.value.guid)){throw 'Сетевой адаптер больше не совпадает с резервной копией'}; if($p.value.auto){Get-DnsClientServerAddress -InterfaceIndex $p.adapter -AddressFamily IPv4 | Set-DnsClientServerAddress -ResetServerAddresses}else{Set-DnsClientServerAddress -InterfaceIndex $p.adapter -ServerAddresses $p.value.servers}",value)
    def activation(self):
        result=self.psjson("@(Get-CimInstance SoftwareLicensingProduct -Filter \"ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f'\" | Where-Object PartialProductKey | Select-Object Name,LicenseStatus) | ConvertTo-Json -Compress",timeout=45) or []

        return result if isinstance(result,list) else [result]

    def elevate(self,directory):
        import sys
        output=self.run(['whoami.exe','/user','/fo','csv','/nh'])
        sid=re.search(r'S-1-(?:[0-9]+-)*[0-9]+',output)
        if not sid:raise RuntimeError('Не удалось определить текущего пользователя')
        launcher=os.environ.get('WINPILOT_EXECUTABLE')
        if launcher and Path(launcher).is_file():
            executable=launcher;args=[]
        elif getattr(sys,'frozen',False):
            executable=sys.executable;args=[]
        else:
            executable=sys.executable;args=[str(Path(__file__).resolve().parents[1]/'main.py')]
        args+=['--wait-instance','--expected-user',sid.group(),'--data-dir',str(directory)]
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
        shell.ShellExecuteW.restype=ctypes.c_void_p
        result=shell.ShellExecuteW(None,'runas',executable,subprocess.list2cmdline(args),str(Path(executable).parent),1)
        if not result or result<=32:raise RuntimeError('Запуск с правами администратора отменён или недоступен')

    def focus_window(self):
        u=ctypes.WinDLL('user32',use_last_error=True)
        callback=ctypes.WINFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_ssize_t)
        u.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
        u.SetForegroundWindow.argtypes=[ctypes.c_void_p];u.ShowWindow.argtypes=[ctypes.c_void_p,ctypes.c_int]
        def found(hwnd,param):
            title=ctypes.create_unicode_buffer(512);u.GetWindowTextW(hwnd,title,512)
            if title.value.startswith('Krolik Control'):
                u.ShowWindow(hwnd,9);u.SetForegroundWindow(hwnd);return 0
            return 1
        cb=callback(found);u.EnumWindows.argtypes=[callback,ctypes.c_ssize_t];u.EnumWindows(cb,0)
    def identify_display(self,ident):
        displays=native.enumerate_displays();d=next((d for d in displays if d['id']==ident),None)
        if not d:raise ValueError('Монитор отключён')
        mode=d['current'].split('@')[0];w,h=map(int,mode.split('x'))
        self.ps("Add-Type -AssemblyName PresentationFramework; $w=New-Object Windows.Window; $w.WindowStyle='None'; $w.ResizeMode='NoResize'; $w.ShowInTaskbar=$false; $w.Topmost=$true; $w.Width=160; $w.Height=140; $w.Left=$p.x; $w.Top=$p.y; $w.Background='#202B40'; $t=New-Object Windows.Controls.TextBlock; $t.Text=[string]$p.number; $t.FontSize=80; $t.Foreground='White'; $t.HorizontalAlignment='Center'; $t.VerticalAlignment='Center'; $w.Content=$t; $timer=New-Object Windows.Threading.DispatcherTimer; $timer.Interval=[TimeSpan]::FromSeconds(2); $timer.Add_Tick({$timer.Stop();$w.Close()}); $timer.Start(); [void]$w.ShowDialog()",{'number':displays.index(d)+1,'x':d['x']+w//2-80,'y':d['y']+h//2-70},timeout=10)
    def active_power_scheme(self):
        match=GUID.search(self.run(['powercfg.exe','/getactivescheme']))
        if not match:raise RuntimeError('Не удалось прочитать текущую схему питания')
        return match.group().lower()
    def local_programs(self):
        from .installed_apps import local_inventory
        return local_inventory()
    def programs(self):
        from .maintenance import program_inventory
        return program_inventory(self)
    def upgrade_app(self,ident):
        try:return self.package_manager.upgrade(ident)
        except Exception as exc:raise user_error(exc,'upgrade') from exc
    def startup(self):
        from .maintenance import startup_inventory
        return startup_inventory(self)
    def set_startup(self,ident,enabled):
        from .maintenance import set_startup
        return set_startup(self,ident,enabled)
    def network_test(self):
        return self.psjson(r"""
$adapters=@(Get-NetIPConfiguration | ForEach-Object {@{name=$_.InterfaceAlias; ipv4=@($_.IPv4Address.IPAddress); gateway=@($_.IPv4DefaultGateway.NextHop); dns=@($_.DNSServer.ServerAddresses)}})
$dns=$false; $tcp=$false; $message=''
try{$records=@(Resolve-DnsName www.microsoft.com -DnsOnly -QuickTimeout -ErrorAction Stop);$dns=$records.Count -gt 0}catch{$message='DNS не ответил'}
try{$client=New-Object Net.Sockets.TcpClient;$job=$client.ConnectAsync('www.microsoft.com',443);$tcp=$job.Wait(4000) -and $client.Connected;$client.Dispose()}catch{$message=if($message){$message+'; нет TCP-соединения по порту 443'}else{'Нет TCP-соединения по порту 443'}}
@{adapters=$adapters;dns=$dns;https=$tcp;message=$message;checked=(Get-Date).ToString('o')} | ConvertTo-Json -Depth 6 -Compress
""",timeout=25)
    def verify_operation(self,op):
        key,value=op['key'],op['value'];kind=op['kind'];actual=None;expected=value
        try:
            if kind=='setting':
                if key in REG:
                    actual=self.read_settings().get(key)
                    if actual==value:
                        deferred=key in {'theme','transparency','extensions','hidden','explorer_home','taskbar_align','switch_keys','nav_expand','file_checkboxes','compact_explorer','taskbar_badges'}
                        return {'status':'deferred' if deferred else 'confirmed','message':'Значение сохранено; оболочке может требоваться новый вход' if deferred else 'Значение перечитано и подтверждено'}
                elif key in native.NATIVE_KEYS:actual=native.read_input().get(key)
                elif key=='time_zone':actual=self.psjson('[TimeZoneInfo]::Local.Id|ConvertTo-Json -Compress')
                elif key=='layouts':
                    actual=self.psjson('@(Get-WinUserLanguageList | ForEach-Object {$_.LanguageTag}) | ConvertTo-Json -Compress')
                    expected={'ru-en':['ru-RU','en-US'],'en-ru':['en-US','ru-RU'],'ru':['ru-RU'],'en':['en-US']}[value]
                    if isinstance(actual,str):actual=[actual]
                    actual=[v for v in (actual or []) if v in ('ru-RU','en-US')]
                elif key=='power_plan':actual=self.active_power_scheme()
                elif key in ('screen_ac','screen_dc','sleep_ac','sleep_dc'):
                    sub='SUB_VIDEO' if key.startswith('screen') else 'SUB_SLEEP';setting='VIDEOIDLE' if key.startswith('screen') else 'STANDBYIDLE'
                    vals=re.findall(r'0x([0-9a-fA-F]{8})',self.run(['powercfg.exe','/query','SCHEME_CURRENT',sub,setting]))
                    actual=str(int(vals[-2 if key.endswith('_ac') else -1],16)//60) if len(vals)>=2 else None
                elif key=='dns':
                    actual=self.psjson("@((Get-DnsClientServerAddress -InterfaceIndex $p.id -AddressFamily IPv4).ServerAddresses) | ConvertTo-Json -Compress",{'id':op['adapter']})
                    if value=='auto':
                        auto=self.psjson("$a=Get-NetAdapter -InterfaceIndex $p.id;$path='HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\'+([guid]$a.InterfaceGuid).ToString('B');[string]::IsNullOrWhiteSpace((Get-ItemProperty -LiteralPath $path -Name NameServer -ErrorAction SilentlyContinue).NameServer)|ConvertTo-Json",{'id':op['adapter']})
                        actual=auto;expected=True
                    else:
                        if isinstance(actual,str):actual=[actual]
                        expected={'cloudflare':['1.1.1.1','1.0.0.1'],'google':['8.8.8.8','8.8.4.4']}[value]
            elif kind=='audio_default':
                from .profile_audio import read_default
                actual=read_default(value['flow'],value['role']);expected=key
            elif kind=='brightness':actual=self.get_brightness(key)
            elif kind=='audio':
                from .audio import get_endpoint
                row=get_endpoint(key);actual={k:row[k] for k in ('volume','mute') if k in value};expected={k:value[k] for k in actual}
            elif kind=='startup':
                row=next((r for r in self.startup() if r['id']==key),None);actual=row['enabled'] if row else None
            elif kind=='driver_safety':
                from .driver_safety import verify_manifest
                verify_manifest(op['backup_path']);return {'status':'confirmed','message':'Целостность копии проверена'}
            elif kind=='package_manager':
                actual=bool(self.package_manager.resolve());expected=True
            elif kind=='restore_point':
                seq=op.get('sequence')
                if type(seq)!=int or seq<1:return {'status':'unverified','message':'Не сохранён номер новой точки восстановления'}
                actual=self.psjson("[bool]@(Get-ComputerRestorePoint|Where-Object {$_.SequenceNumber -eq $p.sequence -and $_.Description -eq 'Krolik Control before changes'}).Count|ConvertTo-Json",{'sequence':seq},timeout=30);expected=True
            elif kind=='update':
                if not re.fullmatch(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}',key) or type(value)!=int:raise ValueError('Неверный идентификатор обновления')
                found=self.psjson("$s=New-Object -ComObject Microsoft.Update.Session;$r=$s.CreateUpdateSearcher().Search(\"UpdateID='$($p.id)' and RevisionNumber=$($p.revision)\");@{found=($r.Updates.Count -eq 1);installed=if($r.Updates.Count -eq 1){[bool]$r.Updates.Item(0).IsInstalled}else{$false}}|ConvertTo-Json -Compress",{'id':key,'revision':value},timeout=60)
                if found and found.get('installed'):return {'status':'confirmed','message':'Windows Update подтвердил установленное обновление'}
                return {'status':'deferred' if op.get('reboot') else 'unverified','message':'Для завершения нужна перезагрузка и повторная проверка' if op.get('reboot') else 'Windows Update пока не подтвердил установленное состояние'}
            elif kind in ('app','upgrade'):
                if kind=='upgrade':
                    row=next((r for r in self.local_programs() if r['id']==key and r.get('installed')),None)
                    actual_version=(row or {}).get('version')
                    if op.get('expected_version') and (actual_version==op['expected_version'] or any(i.get('version')==op['expected_version'] for i in (row or {}).get('installations',[]))):return {'status':'confirmed','message':'Новая версия найдена в Windows'}
                    if op.get('installer_reboot'):return {'status':'deferred','message':'Завершите перезагрузку, затем проверьте версию'}
                    return {'status':'unverified','message':'Установщик завершился; выбранная новая версия пока не подтверждена'}
                try:self.package_manager._command(['list','--id',key,'--exact','--source','winget','--accept-source-agreements','--disable-interactivity'],timeout=120)
                except Exception:return {'status':'unverified','message':'Установщик завершился; проверить наличие программы пока не удалось'}
                return {'status':'confirmed','message':'Программа найдена в Windows'}
            elif kind=='languages':
                actual=self.psjson('@(Get-WinUserLanguageList | ForEach-Object {$_.LanguageTag}) | ConvertTo-Json -Compress')
                if isinstance(actual,str):actual=[actual]
            elif kind=='layout':
                current={d['id']:d for d in native.enumerate_displays()}
                actual=[{'id':r['id'],'x':current[r['id']]['x'],'y':current[r['id']]['y'],'primary':current[r['id']]['primary']} for r in value]
            elif kind=='display':
                row=next((d for d in native.enumerate_displays() if d['id']==key),None);actual=(row['current'],row['orientation']) if row else None
                if op.get('original_orientation',op['orientation'])%2!=op['orientation']%2:
                    dimensions,hz=value.split('@');w,h=dimensions.split('x');value=f'{h}x{w}@{hz}'
                expected=(value,op['orientation'])
            else:return {'status':'unverified','message':'Операция завершена; состояние обновляется отдельно'}
            if actual is None:return {'status':'unverified','message':'Команда выполнена, но повторное чтение недоступно'}
            return {'status':'confirmed' if actual==expected else 'rejected','message':'Значение перечитано и подтверждено' if actual==expected else 'Повторное чтение не подтвердило выбранное значение'}
        except Exception as exc:return {'status':'unverified','message':'Не удалось подтвердить результат: '+str(exc)[:200]}

    def set_languages(self,tags):
        self.ps("$old=Get-WinUserLanguageList;$l=New-WinUserLanguageList $p.tags[0];$l.Clear();foreach($tag in $p.tags){$entry=@($old | Where-Object LanguageTag -eq $tag);if($entry.Count){$l.Add($entry[0])}else{$l.Add((New-WinUserLanguageList $tag)[0])}};Set-WinUserLanguageList $l -Force;if($l[0].InputMethodTips.Count){Set-WinDefaultInputMethodOverride -InputTip $l[0].InputMethodTips[0]}",{'tags':tags})

    def verify_undo(self,v):
        kind=v['kind'];actual=None;expected=v.get('value')
        try:
            if kind=='registry':
                import winreg as R
                for r in v['values']:
                    try:
                        with R.OpenKey(R.HKEY_CURRENT_USER,r['path']) as h:value,t=R.QueryValueEx(h,r['name'])
                    except FileNotFoundError:
                        if r['exists']:raise ValueError('Значение реестра отсутствует')
                        continue
                    if not r['exists'] or value!=r['value'] or t!=r['kind']:raise ValueError('Реестр не совпал с резервной копией')
                return {'status':'confirmed','message':'Сохранённые значения перечитаны'}
            if kind=='mouse_params':actual=native.get_mouse_params()
            elif kind=='setting':
                actual=self.active_power_scheme() if v['key']=='power_plan' else self.psjson('[TimeZoneInfo]::Local.Id|ConvertTo-Json -Compress') if v['key']=='time_zone' else native.read_input().get(v['key'])
            elif kind=='power_seconds':
                sub='SUB_VIDEO' if v['key'].startswith('screen') else 'SUB_SLEEP';option='VIDEOIDLE' if v['key'].startswith('screen') else 'STANDBYIDLE'
                vals=re.findall(r'0x([0-9a-fA-F]{8})',self.run(['powercfg.exe','/query',v.get('scheme') or 'SCHEME_CURRENT',sub,option]))
                actual=str(int(vals[-2 if v['key'].endswith('ac') else -1],16)) if len(vals)>=2 else None
            elif kind=='audio':
                from .audio import get_endpoint
                row=get_endpoint(v['key']);actual=row['mute']==expected['mute'] and abs(row['scalar']-expected['scalar'])<.0001;expected=True
            elif kind=='audio_default':
                from .profile_audio import read_default
                actual=read_default(v['flow'],v['role'])
            elif kind=='brightness':actual=self.get_brightness(v['key'])
            elif kind=='startup':actual=next((r['enabled'] for r in self.startup() if r['id']==v['key']),None)
            elif kind=='languages':
                actual=self.psjson("@{languages=@(Get-WinUserLanguageList | Select-Object LanguageTag,InputMethodTips); tip=(Get-WinDefaultInputMethodOverride).InputMethodTip} | ConvertTo-Json -Depth 6 -Compress")
            elif kind=='dns':
                actual=self.psjson("$a=Get-NetAdapter -InterfaceIndex $p.id;$path='HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\'+([guid]$a.InterfaceGuid).ToString('B');$n=(Get-ItemProperty -LiteralPath $path -Name NameServer -ErrorAction SilentlyContinue).NameServer;@{auto=[string]::IsNullOrWhiteSpace($n);servers=@((Get-DnsClientServerAddress -InterfaceIndex $p.id -AddressFamily IPv4).ServerAddresses)} | ConvertTo-Json -Compress",{'id':v['adapter']})
                actual=actual.get('auto')==expected['auto'] and (expected['auto'] or actual.get('servers')==expected['servers']);expected=True
            if actual is None:raise ValueError('Источник значения недоступен')
            if actual!=expected:raise ValueError('Значение после возврата не совпало с резервной копией')
            return {'status':'confirmed','message':'Возврат перечитан и подтверждён'}
        except Exception as exc:return {'status':'unverified','message':'Не удалось подтвердить возврат: '+str(exc)[:250]}
