"""Capability-based OEM BIOS bridge. No raw NVRAM, flash tools or kernel driver.

Only enumerated, explicitly classified settings are writable. A durable intent
precedes every OEM call; acceptance is not reported as effective before reboot.
"""
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from .workspace import atomic_json

# Exact normalized names, never a substring match for security/boot attributes.
SETTING_TYPES={
    'xmp':('memory','Профиль XMP'), 'xmpprofile':('memory','Профиль XMP'),
    'extremememoryprofile':('memory','Профиль XMP'),
    'expo':('memory','Профиль EXPO'), 'expoprofile':('memory','Профиль EXPO'),
    'memoryprofile':('memory','Профиль памяти'),
    'memoryoverclocking':('memory','Разгон памяти'),
    'fnctrlkeyswap':('keyboard','Поменять Fn и Ctrl'),
    'usbpower':('usb','Питание USB'), 'alwaysonusb':('usb','Питание USB во сне'),
    'usbalwayson':('usb','Питание USB во сне'),
    'wakeonlan':('wake','Пробуждение по сети'),
}

def setting_type(name):
    return SETTING_TYPES.get(re.sub('[^a-z0-9]','',name.lower())) if isinstance(name,str) else None

ADAPTER_PS=r'''
function Read-Oem {
 $provider='none';$rows=@();$password=$null;$writer=$false
 $maker=[string](Get-CimInstance Win32_ComputerSystem -OperationTimeoutSec 3 -ErrorAction Stop).Manufacturer
 if($maker -match 'Lenovo'){
  try{
   $all=@(Get-CimInstance -Namespace root/wmi -ClassName Lenovo_BiosSetting -OperationTimeoutSec 3 -ErrorAction Stop)
   $provider='lenovo'
   try{$pw=Get-CimInstance -Namespace root/wmi -ClassName Lenovo_BiosPasswordSettings -OperationTimeoutSec 3 -ErrorAction Stop;if($null -ne $pw.PasswordState){$password=([int]$pw.PasswordState -ne 0)}}catch{}
   try{$writer=(@(Get-CimInstance -Namespace root/wmi -ClassName Lenovo_SetBiosSetting -OperationTimeoutSec 3 -ErrorAction Stop).Count -eq 1) -and (@(Get-CimInstance -Namespace root/wmi -ClassName Lenovo_SaveBiosSettings -OperationTimeoutSec 3 -ErrorAction Stop).Count -eq 1)}catch{}
   $selector=$null;try{$selector=Get-CimInstance -Namespace root/wmi -ClassName Lenovo_GetBiosSelections -OperationTimeoutSec 3 -ErrorAction Stop}catch{}
   foreach($r in $all|Select-Object -First 512){
    $parts=([string]$r.CurrentSetting).Split(',',2);if($parts.Count -ne 2){continue}
    $key=$parts[0].ToLower() -replace '[^a-z0-9]','';if($p.names -cnotcontains $key){continue}
    $choices=@();if($selector){try{$s=Invoke-CimMethod -InputObject $selector -MethodName GetBiosSelections -Arguments @{Item=$parts[0]} -ErrorAction Stop;if($s.return -eq 'Success'){$choices=@(([string]$s.Selections).Split(','))}}catch{}}
    $rows+=@{name=$parts[0];current=($parts[1].Split(';')[0]);choices=$choices;readonly=$false;physical=$false}
   }
  }catch{}
 }elseif($maker -match 'Dell'){
  try{
   $all=@(Get-CimInstance -Namespace root/dcim/sysman/biosattributes -ClassName EnumerationAttribute -OperationTimeoutSec 3 -ErrorAction Stop);$provider='dell'
   try{$pw=@(Get-CimInstance -Namespace root/dcim/sysman/wmisecurity -ClassName PasswordObject -OperationTimeoutSec 3 -ErrorAction Stop);if($pw.Count){$password=(@($pw|Where-Object {$_.IsPasswordSet -ne 0}).Count -gt 0)}}catch{}
   try{$writer=@(Get-CimInstance -Namespace root/dcim/sysman/biosattributes -ClassName BIOSAttributeInterface -OperationTimeoutSec 3 -ErrorAction Stop).Count -eq 1}catch{}
   $rows=@($all|Select-Object -First 512|ForEach-Object{@{name=$_.AttributeName;current=$_.CurrentValue;choices=@($_.PossibleValue);readonly=$_.ReadOnly;physical=$false}})
  }catch{}
 }elseif($maker -match 'HP|Hewlett'){
  try{
   $all=@(Get-CimInstance -Namespace root/HP/InstrumentedBIOS -ClassName HP_BIOSEnumeration -OperationTimeoutSec 3 -ErrorAction Stop);$provider='hp'
   try{$pw=@(Get-CimInstance -Namespace root/HP/InstrumentedBIOS -ClassName HP_BIOSPassword -OperationTimeoutSec 3 -ErrorAction Stop);if($pw.Count){$password=(@($pw|Where-Object {$_.IsSet -ne 0}).Count -gt 0)}}catch{}
   try{$writer=@(Get-CimInstance -Namespace root/HP/InstrumentedBIOS -ClassName HP_BIOSSettingInterface -OperationTimeoutSec 3 -ErrorAction Stop).Count -eq 1}catch{}
   $rows=@($all|Select-Object -First 512|ForEach-Object{@{name=$_.Name;current=$_.CurrentValue;choices=@($_.PossibleValues);readonly=$_.IsReadOnly;physical=$_.RequiresPhysicalPresence}})
  }catch{}
 }
 @{provider=$provider;rows=$rows;password=$password;writer=$writer}
}
'''

INVENTORY_PS=ADAPTER_PS+r'''
$notes=@()
function Read-Class($name){try{@(Get-CimInstance -ClassName $name -OperationTimeoutSec 3 -ErrorAction Stop)}catch{$script:notes+='Часть сведений не предоставлена Windows';@()}}
$bios=@(Read-Class 'Win32_BIOS'|Select-Object -First 1|ForEach-Object{@{vendor=$_.Manufacturer;version=$_.SMBIOSBIOSVersion;date=if($_.ReleaseDate){$_.ReleaseDate.ToString('yyyy-MM-dd')}else{''}}})
$board=@(Read-Class 'Win32_BaseBoard'|Select-Object -First 1|ForEach-Object{@{vendor=$_.Manufacturer;model=$_.Product}})
$system=@(Read-Class 'Win32_ComputerSystem'|Select-Object -First 1|ForEach-Object{@{vendor=$_.Manufacturer;model=$_.Model;hypervisor=$_.HypervisorPresent}})
$cpu=@(Read-Class 'Win32_Processor'|Select-Object -First 8|ForEach-Object{@{name=$_.Name;virtualization=$_.VirtualizationFirmwareEnabled;slat=$_.SecondLevelAddressTranslationExtensions}})
$memory=@(Read-Class 'Win32_PhysicalMemory'|Select-Object -First 32|ForEach-Object{@{slot=$_.DeviceLocator;bank=$_.BankLabel;part=$_.PartNumber;vendor=$_.Manufacturer;bytes=[double]$_.Capacity;configured=$_.ConfiguredClockSpeed;type=$_.SMBIOSMemoryType;voltage=$_.ConfiguredVoltage}})
$boot='';try{$boot=(Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 3 -ErrorAction Stop).LastBootUpTime.ToUniversalTime().ToString('o')}catch{}
$secure=$null;try{$secure=[bool](Confirm-SecureBootUEFI -ErrorAction Stop)}catch{}
$tpm=$null;try{$t=Get-Tpm -ErrorAction Stop;$tpm=@{present=$t.TpmPresent;ready=$t.TpmReady}}catch{}
$encryption=$null;try{$v=Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop;if([int]$v.ProtectionStatus -in @(0,1)){$encryption=([int]$v.ProtectionStatus -eq 1)}}catch{}
@{bios=$bios;board=$board;system=$system;cpu=$cpu;memory=$memory;boot=$boot;secure_boot=$secure;tpm=$tpm;encryption=$encryption;oem=(Read-Oem);notes=$notes}|ConvertTo-Json -Depth 8 -Compress
'''

WRITE_PS=ADAPTER_PS+r'''
$o=Read-Oem
if($o.provider -cne $p.provider -or !$o.writer -or $o.password -ne $false -or $null -eq $o.password){throw 'Доступ к записи BIOS не подтверждён'}
$r=@($o.rows|Where-Object {$_.name -ceq $p.name})
if($r.Count -ne 1 -or $r[0].readonly -or $r[0].physical -or $r[0].current -cne $p.before -or @($r[0].choices) -cnotcontains $p.value){throw 'Параметр BIOS изменился или недоступен'}
if($p.provider -eq 'lenovo'){
 $s=Get-CimInstance -Namespace root/wmi -ClassName Lenovo_SetBiosSetting -ErrorAction Stop
 $result=Invoke-CimMethod -InputObject $s -MethodName SetBiosSetting -Arguments @{parameter=($p.name+','+$p.value)} -ErrorAction Stop
 if($result.return -cne 'Success'){@{accepted=$false;code=[string]$result.return;stage='set'}|ConvertTo-Json -Compress;exit}
 $s=Get-CimInstance -Namespace root/wmi -ClassName Lenovo_SaveBiosSettings -ErrorAction Stop
 $result=Invoke-CimMethod -InputObject $s -MethodName SaveBiosSettings -ErrorAction Stop
 @{accepted=($result.return -ceq 'Success');code=[string]$result.return;stage='save'}|ConvertTo-Json -Compress
}elseif($p.provider -eq 'dell'){
 $s=Get-CimInstance -Namespace root/dcim/sysman/biosattributes -ClassName BIOSAttributeInterface -ErrorAction Stop
 $result=Invoke-CimMethod -InputObject $s -MethodName SetAttribute -Arguments @{SecType=[uint32]0;SecHndCount=[uint32]0;SecHandle=[byte[]]@(0);AttributeName=$p.name;AttributeValue=$p.value} -ErrorAction Stop
 @{accepted=($null -ne $result.Status -and $result.Status -eq 0);code=[string]$result.Status;stage='set'}|ConvertTo-Json -Compress
}elseif($p.provider -eq 'hp'){
 $s=Get-CimInstance -Namespace root/HP/InstrumentedBIOS -ClassName HP_BIOSSettingInterface -ErrorAction Stop
 $result=Invoke-CimMethod -InputObject $s -MethodName SetBIOSSetting -Arguments @{Name=$p.name;Value=$p.value;Password='<utf-16/>'} -ErrorAction Stop
 @{accepted=($null -ne $result.Return -and $result.Return -eq 0);code=[string]$result.Return;stage='set'}|ConvertTo-Json -Compress
}else{throw 'Неподдерживаемый интерфейс'}
'''

def firmware_mode():
    if os.name!='nt':return None
    try:
        k=ctypes.WinDLL('kernel32',use_last_error=True);value=ctypes.c_uint32()
        if k.GetFirmwareType(ctypes.byref(value)):return {1:'legacy',2:'uefi'}.get(value.value)
    except (OSError,AttributeError):pass
    return None

def text(v,limit=160):return v.strip()[:limit] if isinstance(v,str) else ''
def numeric(v,low,high):return v if type(v) in (int,float) and low<=v<=high else None
def flag(v):return v if type(v)==bool else None
def rows(raw,key,limit=32):return [r for r in raw.get(key,[])[:limit] if isinstance(r,dict)] if isinstance(raw.get(key),list) else []

def normalize(raw,mode):
    if not isinstance(raw,dict):raise ValueError('Нет сведений о прошивке')
    result={k:[{f:text(r.get(f)) for f in fields} for r in rows(raw,k)] for k,fields in [('bios',['vendor','version','date']),('board',['vendor','model']),('system',['vendor','model'])]}
    result.update(mode=mode,boot=text(raw.get('boot')),secure_boot=flag(raw.get('secure_boot')),encryption=flag(raw.get('encryption')),tpm=None,cpu=[],memory=[],settings=[])
    if isinstance(raw.get('tpm'),dict):result['tpm']={k:flag(raw['tpm'].get(k)) for k in ('present','ready')}
    for r in rows(raw,'cpu',8):result['cpu'].append({'name':text(r.get('name')),'virtualization':flag(r.get('virtualization')),'slat':flag(r.get('slat'))})
    for i,r in enumerate(rows(raw,'memory')):
        result['memory'].append({'slot':text(r.get('slot')) or 'Модуль '+str(i+1),'bank':text(r.get('bank')),'part':text(r.get('part')),'vendor':text(r.get('vendor')),'bytes':numeric(r.get('bytes'),1,2**50),'configured':numeric(r.get('configured'),100,30000),'type':numeric(r.get('type'),1,255),'voltage':numeric(r.get('voltage'),500,3000)})
    o=raw.get('oem') if isinstance(raw.get('oem'),dict) else {}
    provider=o.get('provider') if o.get('provider') in ('lenovo','dell','hp') else 'none'
    result.update(provider=provider,password=flag(o.get('password')),writer=o.get('writer') is True)
    seen=set();oem_rows=rows(o,'rows',512)
    counts={text(r.get('name')):sum(text(x.get('name'))==text(r.get('name')) for x in oem_rows) for r in oem_rows if setting_type(text(r.get('name')))}
    for r in oem_rows:
        name=text(r.get('name'));kind=setting_type(name)
        if not kind or not name or name in seen:continue
        seen.add(name);current=text(r.get('current'))
        choices=list(dict.fromkeys(c for c in r.get('choices',[]) if isinstance(c,str) and 0<len(c)<=160 and not re.search(r'[,;\x00-\x1f]',c)))[:32] if isinstance(r.get('choices'),list) else []
        # OEMs occasionally omit access metadata; fail closed for those rows.
        writable=counts.get(name)==1 and provider!='none' and result['writer'] and result['password'] is False and r.get('readonly') in (False,0) and r.get('physical') in (False,0) and len(choices)>1 and current in choices and not re.search(r'[,;\x00-\x1f]',name)
        result['settings'].append({'name':name,'current':current,'choices':choices,'kind':kind[0],'title':kind[1],'writable':writable})
    return result

def demo_inventory():
    return normalize({'bios':[{'vendor':'American Megatrends','version':'1.A0','date':'2025-04-02'}],'board':[{'vendor':'MSI','model':'B650 Gaming Plus'}],'system':[{'vendor':'Custom','model':'Desktop PC'}],'cpu':[{'name':'AMD Ryzen 7 7800X3D','virtualization':True,'slat':True}],'memory':[{'slot':'DIMMA2','part':'FURY DDR5','vendor':'Kingston','bytes':16*1024**3,'configured':6000,'type':34,'voltage':1350},{'slot':'DIMMB2','part':'FURY DDR5','vendor':'Kingston','bytes':16*1024**3,'configured':6000,'type':34,'voltage':1350}],'boot':'demo-boot','secure_boot':True,'encryption':False,'tpm':{'present':True,'ready':True},'oem':{'provider':'none'}},'uefi')

def fingerprint(data):
    # Board+module model binding, not a machine serial number or recovery key.
    value={k:data.get(k) for k in ('bios','board','system','boot','settings','encryption','memory','mode')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def machine(data):
    return {k:data.get(k) for k in ('board','system')}

def valid_record(r):
    if not isinstance(r,dict) or type(r.get('version'))!=int or r['version']!=1 or set(r)-{'version','baseline','change'}:return False
    for key in ('baseline','change'):
        if key not in r:continue
        v=r[key]
        if not isinstance(v,dict) or numeric(v.get('time'),1,10**11) is None or not isinstance(v.get('boot'),str) or not isinstance(v.get('machine'),dict):return False
        if key=='baseline':
            if not isinstance(v.get('memory'),list) or len(v['memory'])>32 or not isinstance(v.get('bios'),list):return False
            if any(not isinstance(m,dict) or not isinstance(m.get('slot'),str) or not isinstance(m.get('part'),str) or m.get('configured') is not None and numeric(m['configured'],100,30000) is None for m in v['memory']):return False
        else:
            if v.get('state') not in ('prepared','accepted','uncertain','verified','mismatch','unavailable') or v.get('provider') not in ('lenovo','dell','hp'):return False
            if not setting_type(v.get('name')) or any(not isinstance(v.get(k),str) or len(v[k])>160 for k in ('name','title','before','after')):return False
    return True

class FirmwareCenter:
    def __init__(self,app,directory):
        self.app=app;self.lock=threading.RLock();self.directory=Path(directory);self.intent=None
        self.path=self.directory/('firmware-demo.json' if app.demo else 'firmware.json')
        self.record={};self.warning=''
        try:
            if self.path.exists():
                if self.path.stat().st_size>65536:raise ValueError('large')
                r=json.loads(self.path.read_text(encoding='utf-8'))
                if not valid_record(r):raise ValueError('schema')
                self.record=r
        except (OSError,ValueError):self.warning='Сохранённые сведения BIOS повреждены. Запись заблокирована.'
    def _read(self):
        return demo_inventory() if self.app.demo else normalize(self.app.backend.psjson(INVENTORY_PS,{'names':list(SETTING_TYPES)},timeout=55),firmware_mode())
    def scan(self):
        data=self._read()
        with self.lock:
            self._verify(data)
            return {**data,'saved':copy.deepcopy(self.record),'warning':self.warning,'scanned_at':time.time()}
    def _save(self):atomic_json(self.path,self.record)
    def _verify(self,data):
        j=self.record.get('change')
        if not isinstance(j,dict) or j.get('state') not in ('prepared','accepted','uncertain') or not data.get('boot') or not j.get('boot') or data['boot']==j['boot']:return
        if j.get('machine')!=machine(data):return
        row=next((r for r in data['settings'] if r['name']==j.get('name')),None)
        state='verified' if row and row['current']==j.get('after') else 'mismatch' if row else 'unavailable'
        self.record['change']={**j,'state':state,'observed':row['current'] if row else None};self._save()
    def baseline(self):
        data=self._read()
        if not data['memory']:raise ValueError('Сначала нужно прочитать установленные модули памяти')
        with self.lock:
            self.record={**self.record,'version':1,'baseline':{'time':time.time(),'machine':machine(data),'boot':data['boot'],'bios':data['bios'],'memory':data['memory']}}
            self._save()
        return {**data,'saved':copy.deepcopy(self.record),'warning':self.warning,'scanned_at':time.time()}
    def _guard(self):
        if self.warning:raise ValueError(self.warning)
        if not self.app.demo and not self.app.backend.is_admin():raise ValueError('Перезапустите Krolik Control от имени администратора')
        if self.app.engine.snapshot()['running'] or self.app.care.state['running'] or any(t.get('status')=='running' for t in self.app.tasks.values()):raise ValueError('Дождитесь завершения текущей операции')
        if self.app.backend.display_guard.status():raise ValueError('Сначала подтвердите режим экрана')
    def preview(self,body):
        self._guard();data=copy.deepcopy(self.app.data.get('firmware'))
        if not data or time.time()-data.get('scanned_at',0)>120:raise ValueError('Обновите сведения BIOS перед подтверждением')
        with self.lock:
            self._verify(data)
            if body.get('action')=='restart':
                if body.get('target') not in ('uefi','windows'):raise ValueError('Неизвестный вид перезагрузки')
                if body['target']=='uefi' and data['mode']!='uefi':raise ValueError('Загрузка Windows в режиме UEFI не подтверждена')
                intent={'action':'restart','target':body['target']}
            elif body.get('action')=='setting':
                j=self.record.get('change') or {}
                if j.get('state') in ('prepared','accepted','uncertain'):raise ValueError('Сначала перезагрузите ПК и проверьте предыдущее изменение')
                row=next((r for r in data['settings'] if r['name']==body.get('name')),None)
                if not row or not row['writable'] or body.get('value') not in row['choices']:raise ValueError('Эта настройка не предоставлена BIOS для изменения')
                if body['value']==row['current']:raise ValueError('Это значение уже выбрано')
                if not data['boot']:raise ValueError('Не удалось определить загрузку Windows для проверки результата')
                intent={'action':'setting','provider':data['provider'],'name':row['name'],'before':row['current'],'value':body['value'],'kind':row['kind'],'title':row['title']}
            else:raise ValueError('Неизвестное действие BIOS')
            intent.update(token=secrets.token_urlsafe(32),expires=time.monotonic()+120,fingerprint=fingerprint(data),encryption=data['encryption'])
            self.intent=intent
            return {**{k:v for k,v in intent.items() if k not in ('expires','fingerprint')},'recovery_required':data['encryption'] is not False,'demo':self.app.demo}
    def consume(self,body):
        self._guard()
        with self.lock:
            i=self.intent
            if not i or not isinstance(body.get('token'),str) or not secrets.compare_digest(body['token'],i['token']) or time.monotonic()>i['expires']:raise ValueError('Подтверждение устарело. Проверьте действие снова.')
            if body.get('confirmed') is not True:raise ValueError('Подтвердите действие')
            if i['encryption'] is not False and body.get('recovery_saved') is not True:raise ValueError('Подтвердите доступ к ключу восстановления шифрования')
            if i.get('kind')=='memory' and body.get('memory_ack') is not True:raise ValueError('Подтвердите настройку профиля памяти')
            self.intent=None
            return copy.deepcopy(i)
    def execute(self,i):
        data=self._read()
        if fingerprint(data)!=i['fingerprint']:raise ValueError('Сведения BIOS изменились. Заново проверьте выбранное действие.')
        if not self.app.demo and not self.app.backend.is_admin():raise ValueError('Нужны права администратора')
        if i['action']=='restart':
            if self.app.demo:return {'message':'Демонстрация: перезагрузка не выполнялась','demo':True}
            # /t > 0 implies /f in shutdown.exe. Never use a timed forced reboot.
            args=[str(Path(os.environ['SystemRoot'])/'System32/shutdown.exe'),'/r','/t','0']
            if i['target']=='uefi':args+=['/fw']
            self.app.backend.run(args,timeout=15)
            return {'message':'Запрос на перезагрузку передан Windows. Открытые приложения могут его остановить.'}
        with self.lock:
            self.record={**self.record,'version':1,'change':{'state':'prepared','time':time.time(),'boot':data['boot'],'machine':machine(data),'provider':i['provider'],'name':i['name'],'title':i['title'],'before':i['before'],'after':i['value']}}
            self._save()  # If persistence fails, no firmware write is attempted.
        try:
            result={'accepted':True,'code':'Demo','stage':'set'} if self.app.demo else self.app.backend.psjson(WRITE_PS,{'names':list(SETTING_TYPES),**{k:i[k] for k in ('provider','name','before','value')}},timeout=40)
            accepted=isinstance(result,dict) and result.get('accepted') is True
            state='accepted' if accepted else 'uncertain'
            with self.lock:
                self.record['change'].update(state=state,code=text(result.get('code')) if isinstance(result,dict) else '')
                self._save()
            if not accepted:raise ValueError('BIOS не подтвердил сохранение. Повторная запись заблокирована до перезагрузки и проверки.')
        except Exception:
            with self.lock:
                self.record['change']['state']='uncertain';self._save()
            raise ValueError('Не удалось подтвердить запись BIOS. Перезагрузите ПК и проверьте результат; повторять запись автоматически нельзя.') from None
        return {'message':'BIOS принял настройку. Перезагрузите ПК, затем откройте этот раздел для проверки.','saved':copy.deepcopy(self.record),'demo':self.app.demo}
