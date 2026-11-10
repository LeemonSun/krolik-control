"""Read-only PC overview. Live probes have a short lease and no installed service."""
import copy
import ctypes
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

HARDWARE_PS=r'''
$errors=@()
function Read-Class($name){try{@(Get-CimInstance -ClassName $name -OperationTimeoutSec 3 -ErrorAction Stop)}catch{$script:errors+=('Не удалось прочитать '+$name);@()}}
$cpu=@(Read-Class 'Win32_Processor'|Select-Object -First 8|ForEach-Object{@{name=$_.Name;cores=$_.NumberOfCores;threads=$_.NumberOfLogicalProcessors}})
$gpu=@(Read-Class 'Win32_VideoController'|Select-Object -First 8|ForEach-Object{@{name=$_.Name;driver=$_.DriverVersion;status=$_.Status}})
$memory=@(Read-Class 'Win32_PhysicalMemory'|Select-Object -First 32|ForEach-Object{@{bytes=[double]$_.Capacity;speed=$_.ConfiguredClockSpeed;manufacturer=$_.Manufacturer;part=$_.PartNumber}})
$board=@(Read-Class 'Win32_BaseBoard'|Select-Object -First 2|ForEach-Object{@{manufacturer=$_.Manufacturer;name=$_.Product}})
$system=@(Read-Class 'Win32_ComputerSystem'|Select-Object -First 1|ForEach-Object{@{manufacturer=$_.Manufacturer;model=$_.Model;type=$_.PCSystemType}})
$disks=@()
try{$disks=@(Get-PhysicalDisk -ErrorAction Stop|Select-Object -First 12|ForEach-Object{
 $d=$_;$r=$null;try{$r=$d|Get-StorageReliabilityCounter -ErrorAction Stop}catch{}
 @{name=$d.FriendlyName;bytes=[double]$d.Size;bus=[string]$d.BusType;media=[string]$d.MediaType;health=[string]$d.HealthStatus;temperature=if($r){$r.Temperature}else{$null};wear=if($r){$r.Wear}else{$null};errors=if($r -and $null -ne $r.ReadErrorsUncorrected -and $null -ne $r.WriteErrorsUncorrected){[double]$r.ReadErrorsUncorrected+[double]$r.WriteErrorsUncorrected}else{$null}}
})}catch{$errors+='Windows не предоставила сведения накопителей'}
@{cpu=$cpu;gpu=$gpu;memory=$memory;board=$board;system=$system;disks=$disks;notes=$errors}|ConvertTo-Json -Depth 7 -Compress
'''

LIVE_PS=r'''
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$WarningPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$namespace=$null;$retry=0
while($true){
 $gpu=$null;$sensors=@();$hardware=@();$adapters=@()
 try{
  $engines=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -OperationTimeoutSec 2 -ErrorAction Stop|Where-Object {$_.Name -match 'engtype_3D'}
  $groups=@{};foreach($g in $engines){$key=$g.Name -replace '^pid_\d+_','';if(!$groups.ContainsKey($key)){$groups[$key]=0.0};$groups[$key]+=[double]$g.UtilizationPercentage}
  if($groups.Count){$gpu=[Math]::Min(100,($groups.Values|Measure-Object -Maximum).Maximum);$cards=@{};foreach($key in $groups.Keys){if($key -match '(luid_0x[0-9a-f]+_0x[0-9a-f]+)'){$card=$matches[1].ToLower();if(!$cards.ContainsKey($card)){$cards[$card]=0.0};$cards[$card]=[Math]::Max($cards[$card],$groups[$key])}};$adapters=@($cards.Keys|ForEach-Object{@{key=$_;load=[Math]::Min(100,$cards[$_])}})}
 }catch{}
 if(!$namespace -and $retry -le 0){foreach($n in @('root/LibreHardwareMonitor','root/OpenHardwareMonitor')){try{$null=Get-CimInstance -Namespace $n -ClassName Sensor -OperationTimeoutSec 2 -ErrorAction Stop;$namespace=$n;break}catch{}};$retry=10};$retry--
 if($namespace){try{
  $sensors=@(Get-CimInstance -Namespace $namespace -ClassName Sensor -OperationTimeoutSec 2 -ErrorAction Stop|Where-Object SensorType -eq 'Temperature'|Select-Object -First 64|ForEach-Object{@{name=$_.Name;parent=$_.Parent;value=$_.Value}})
  $hardware=@(Get-CimInstance -Namespace $namespace -ClassName Hardware -OperationTimeoutSec 2 -ErrorAction Stop|Select-Object -First 64|ForEach-Object{@{id=$_.Identifier;name=$_.Name;type=[string]$_.HardwareType}})
 }catch{$namespace=$null}}
 @{gpu=$gpu;adapters=$adapters;sensors=$sensors;hardware=$hardware;source=$namespace}|ConvertTo-Json -Depth 5 -Compress
 Start-Sleep -Seconds 3
}
'''

EVENTS_PS=r'''
$events=@(Get-WinEvent -FilterHashtable @{LogName=@('System','Application');Level=@(1,2);StartTime=(Get-Date).AddDays(-7)} -MaxEvents 30 -ErrorAction SilentlyContinue|ForEach-Object{
 $text=[string]$_.Message;if($text.Length -gt 1600){$text=$text.Substring(0,1600)}
 @{id=$_.Id;source=$_.ProviderName;time=$_.TimeCreated.ToUniversalTime().ToString('o');message=$text}
});@{events=$events}|ConvertTo-Json -Depth 5 -Compress
'''

def number(value,low=0,high=100):
    return float(value) if type(value) in (int,float) and math.isfinite(value) and low<=value<=high else None

def temperatures(raw):
    if not isinstance(raw,dict):return []
    source_hardware=raw.get('hardware');sensors=raw.get('sensors')
    hardware={str(h.get('id','')).lower():h for h in source_hardware[:64] if isinstance(h,dict)} if isinstance(source_hardware,list) else {}
    if not isinstance(sensors,list):return []
    result=[]
    for s in sensors[:64]:
        if not isinstance(s,dict):continue
        parent=str(s.get('parent','')).lower();h=hardware.get(parent,{})
        typ=str(h.get('type','')).lower();kind='cpu' if typ=='cpu' or parent.startswith(('/intelcpu/','/amdcpu/','/cpu/')) else 'gpu' if typ.startswith('gpu') or parent.startswith(('/amdgpu/','/nvidiagpu/','/intelgpu/','/gpu-')) else None
        value=number(s.get('value'),1,150)
        if kind and value is not None:result.append({'kind':kind,'celsius':round(value,1),'label':str(s.get('name','Датчик'))[:160],'hardware':str(h.get('name',''))[:200],'source':str(raw.get('source',''))[:80]})
    return result

def vendor_metrics(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('gpu_details'),list):return []
    out=[]
    ranges={'temperature_c':(0,150),'hotspot_c':(0,150),'core_mhz':(0,20000),'memory_mhz':(0,50000),'fan_percent':(0,100),'fan_rpm':(0,20000),'power_mw':(0,2000000),'load':(0,100),'vram_used_bytes':(0,1024**4),'vram_total_bytes':(1,1024**4)}
    for row in raw['gpu_details'][:16]:
        if not isinstance(row,dict) or row.get('source') not in ('NVML','AMD ADL') or not isinstance(row.get('name'),str) or not isinstance(row.get('key'),str):continue
        r={k:str(row.get(k,''))[:256] for k in ('name','key','source','vendor')};r.update({k:number(row.get(k),*bounds) for k,bounds in ranges.items()});bits=row.get('clock_limit_bits');r['clock_limit_bits']=bits if isinstance(bits,str) and bits.isdecimal() and len(bits)<=20 else None;out.append(r)
    return out

class FastCounters:
    def __init__(self):self.previous=None
    def read(self):
        if os.name!='nt':return {'cpu':None,'ram_percent':None,'ram_used_gb':None,'ram_total_gb':None}
        class MEMORY(ctypes.Structure):
            _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[(k,ctypes.c_uint64) for k in ('total','avail','page','availpage','virtual','availvirtual','extended')]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        idle=ctypes.c_uint64();system=ctypes.c_uint64();user=ctypes.c_uint64()
        cpu=None
        if kernel.GetSystemTimes(ctypes.byref(idle),ctypes.byref(system),ctypes.byref(user)):
            row=(idle.value,system.value+user.value)
            if self.previous:
                total=row[1]-self.previous[1];unused=row[0]-self.previous[0]
                if total>0 and 0<=unused<=total:cpu=round(100*(1-unused/total),1)
            self.previous=row
        memory=MEMORY();memory.length=ctypes.sizeof(memory)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):return {'cpu':cpu,'ram_percent':None,'ram_used_gb':None,'ram_total_gb':None}
        return {'cpu':cpu,'ram_percent':round(100*(1-memory.avail/memory.total),1) if memory.total else None,'ram_used_gb':round((memory.total-memory.avail)/1024**3,1),'ram_total_gb':round(memory.total/1024**3,1)}

def volumes():
    if os.name!='nt':return []
    k=ctypes.WinDLL('kernel32',use_last_error=True);result=[]
    k.GetDriveTypeW.argtypes=[ctypes.c_wchar_p]
    k.GetDiskFreeSpaceExW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint64),ctypes.POINTER(ctypes.c_uint64),ctypes.POINTER(ctypes.c_uint64)]
    mask=k.GetLogicalDrives()
    for i in range(26):
        path=chr(65+i)+':\\'
        if not mask&(1<<i) or k.GetDriveTypeW(path)!=3:continue
        available=ctypes.c_uint64();total=ctypes.c_uint64();free=ctypes.c_uint64()
        if k.GetDiskFreeSpaceExW(path,ctypes.byref(available),ctypes.byref(total),ctypes.byref(free)) and total.value:
            result.append({'name':path,'total_gb':round(total.value/1024**3,1),'free_gb':round(available.value/1024**3,1),'used_percent':round(100*(1-free.value/total.value),1)})
    return result

def demo_hardware():
    return {'cpu':[{'name':'AMD Ryzen 7 7800X3D','cores':8,'threads':16}], 'gpu':[{'name':'AMD Radeon RX 6650 XT','driver':'32.0.12033.1030','status':'OK'}], 'memory':[{'bytes':16*1024**3,'speed':6000,'manufacturer':'Kingston','part':'FURY DDR5'} for _ in range(2)], 'board':[{'manufacturer':'MSI','name':'B650 Gaming Plus'}], 'system':[{'manufacturer':'Custom','model':'Desktop PC','type':1}], 'disks':[{'name':'NVMe SSD · пример','bytes':1024**4,'bus':'NVMe','media':'SSD','health':'Healthy','temperature':38,'wear':None,'errors':0}], 'volumes':[{'name':'C:\\','total_gb':930,'free_gb':326,'used_percent':64.9},{'name':'D:\\','total_gb':1863,'free_gb':1240,'used_percent':33.4}], 'notes':[]}

class PcCenter:
    def __init__(self,app):
        self.app=app;self.lock=threading.RLock();self.closed=threading.Event();self.last_seen=0;self.worker=None;self.process=None;self.vendor_process=None;self.last_hardware=0
        self.value={'hardware':None,'hardware_status':'idle','hardware_error':'','live':None,'history':[],'sampled_at':None,'demo':app.demo,'monitoring':False}
    def read(self,refresh=False):
        with self.lock:
            self.last_seen=time.monotonic()
            if self.closed.is_set():return copy.deepcopy(self.value)
            if self.app.engine.snapshot()['running'] or self.app.care.state['running'] or getattr(getattr(self.app,'toolbox',None),'state',{}).get('running',False):
                result=copy.deepcopy(self.value);result['paused']=True;result['monitoring']=False
                result['age_seconds']=round(time.time()-result['sampled_at'],1) if result['sampled_at'] else None
                return result
            if (self.value['hardware_status']=='idle' or refresh and time.monotonic()-self.last_hardware>5) and self.value['hardware_status']!='running':
                self.last_hardware=time.monotonic();self.value['hardware_status']='running';self.value['hardware_error']=''
                threading.Thread(target=self._hardware,daemon=True).start()
            if self.worker is None or not self.worker.is_alive():
                self.worker=threading.Thread(target=self._watch,daemon=True);self.worker.start()
            result=copy.deepcopy(self.value)
            result['age_seconds']=round(time.time()-result['sampled_at'],1) if result['sampled_at'] else None
            return result
    def _hardware(self):
        try:
            if hasattr(self.app.backend,'device_inventory'):
                devices=self.app.backend.device_inventory()
                with self.app.lock:
                    if self.app.info:self.app.info.update(devices);self.app.data_revision+=1
            result=demo_hardware() if self.app.demo else self.app.backend.psjson(HARDWARE_PS,timeout=35)
            if not isinstance(result,dict):raise ValueError('Неполный ответ Windows')
            for name in ('cpu','gpu','memory','board','system','disks','notes'):
                if not isinstance(result.get(name),list):result[name]=[]
                result[name]=result[name][:64]
            if not self.app.demo:
                result['volumes']=volumes()
                helper=Path(__file__).resolve().parents[1]/'krolik-graphics.exe'
                result['graphics']=[]
                if helper.is_file():
                    try:
                        cards=json.loads(self.app.backend.run([str(helper)],timeout=8))
                        if isinstance(cards,list):result['graphics']=[g for g in cards[:16] if isinstance(g,dict) and isinstance(g.get('name'),str) and isinstance(g.get('key'),str)]
                    except (ValueError,OSError,RuntimeError):pass
            with self.lock:self.value.update(hardware=result,hardware_status='done',hardware_error='')
        except Exception:
            with self.lock:self.value.update(hardware_status='error',hardware_error='Часть оборудования не удалось прочитать. Можно повторить проверку.')
    def _start_provider(self,lines):
        executable=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        import base64
        script=f'$owner=[Diagnostics.Process]::GetProcessById({os.getpid()});$null=$owner.Handle;\n'+LIVE_PS.replace('while($true){','while(-not $owner.HasExited){').replace('Start-Sleep -Seconds 3','if($owner.WaitForExit(3000)){break}')
        encoded=base64.b64encode(script.encode('utf-16-le')).decode()
        with self.lock:
            if self.closed.is_set():raise OSError('Мониторинг остановлен')
            p=subprocess.Popen([str(executable),'-NoProfile','-NonInteractive','-EncodedCommand',encoded],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=0x08000000)
            self.process=p
        def pump():
            for line in p.stdout:
                if len(line)>131072:continue
                try:row=json.loads(line.decode('utf-8-sig'))
                except (ValueError,UnicodeError):continue
                try:lines.put_nowait(row)
                except queue.Full:pass
        p.pc_reader=threading.Thread(target=pump,daemon=True);p.pc_reader.start()
        return p
    def _start_vendor(self,lines):
        import sys
        python=Path(sys.executable).with_name('python.exe')
        with self.lock:
            if self.closed.is_set():raise OSError('Мониторинг остановлен')
            from .worker_process import worker_command
            p=subprocess.Popen(worker_command('gpu_sensors',os.getpid()),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=0x08000000);self.vendor_process=p
        def pump():
            for line in p.stdout:
                if len(line)>131072:continue
                try:r=json.loads(line.decode('utf-8-sig'))
                except (ValueError,UnicodeError):continue
                try:lines.put_nowait(r)
                except queue.Full:pass
        p.pc_reader=threading.Thread(target=pump,daemon=True);p.pc_reader.start();return p
    def _watch(self):
        counters=FastCounters();lines=queue.Queue(maxsize=3);provider=None;raw={};last_raw=0;next_provider=0;vendor=None;vendor_lines=queue.Queue(maxsize=2);vendor_raw={};last_vendor=0;next_vendor=0
        try:
            while not self.closed.is_set():
                with self.lock:
                    if time.monotonic()-self.last_seen>8:break
                if self.app.engine.snapshot()['running'] or self.app.care.state['running'] or getattr(getattr(self.app,'toolbox',None),'state',{}).get('running',False):break
                if not self.app.demo and (provider is None or provider.poll() is not None) and time.monotonic()>=next_provider:
                    if provider:
                        provider.pc_reader.join(timeout=1);provider.stdout.close()
                    try:provider=self._start_provider(lines)
                    except (OSError,KeyError):provider=None
                    next_provider=time.monotonic()+20
                if not self.app.demo and os.name=='nt' and (vendor is None or vendor.poll() is not None) and time.monotonic()>=next_vendor:
                    if vendor:vendor.pc_reader.join(timeout=1);vendor.stdout.close()
                    try:vendor=self._start_vendor(vendor_lines)
                    except (OSError,KeyError):vendor=None
                    next_vendor=time.monotonic()+30
                if self.app.demo:
                    phase=int(time.monotonic())%8;row={'cpu':18+phase,'ram_percent':38.4,'ram_used_gb':12.3,'ram_total_gb':32,'gpu':12+phase,'temperatures':[{'kind':'cpu','celsius':48+phase/2,'label':'CPU Package · пример','hardware':'AMD Ryzen 7 7800X3D','source':'demo'},{'kind':'gpu','celsius':45+phase/2,'label':'GPU Core · пример','hardware':'AMD Radeon RX 6650 XT','source':'demo'}]}
                else:
                    try:
                        while True:
                            received=lines.get_nowait()
                            if isinstance(received,dict):raw=received;last_raw=time.monotonic()
                    except queue.Empty:pass
                    if time.monotonic()-last_raw>18:raw={}
                    try:row=counters.read()
                    except OSError:row={'cpu':None,'ram_percent':None,'ram_used_gb':None,'ram_total_gb':None}
                    row.update(gpu=number(raw.get('gpu')),temperatures=temperatures(raw),adapters=[{'key':g['key'],'load':number(g.get('load'))} for g in raw.get('adapters',[])[:16] if isinstance(g,dict) and isinstance(g.get('key'),str)] if isinstance(raw.get('adapters'),list) else [])
                if not self.app.demo:
                    try:
                        while True:
                            received=vendor_lines.get_nowait()
                            if isinstance(received,dict):vendor_raw=received;last_vendor=time.monotonic()
                    except queue.Empty:pass
                    if time.monotonic()-last_vendor>18:vendor_raw={}
                    row['gpu_details']=vendor_metrics(vendor_raw)
                    row['temperatures']+=[{'kind':'gpu','celsius':g['temperature_c'],'label':'GPU · '+g['name'],'hardware':g['name'],'source':g['source']} for g in row['gpu_details'] if g['temperature_c'] is not None]
                stamp=time.time()
                with self.lock:
                    self.value.update(live=row,sampled_at=stamp,monitoring=True)
                    thermal={kind+'_temperature':max((t['celsius'] for t in row['temperatures'] if t['kind']==kind),default=None) for kind in ('cpu','gpu')}
                    self.value['history']=(self.value['history']+[{'time':stamp,'cpu':row['cpu'],'ram_percent':row['ram_percent'],'gpu':row['gpu'],**thermal}])[-45:]
                self.closed.wait(2)
        finally:
            if provider:
                if provider.poll() is None:provider.kill()
                try:provider.wait(timeout=3)
                except subprocess.TimeoutExpired:pass
                provider.pc_reader.join(timeout=1)
                provider.stdout.close()
            if vendor:
                if vendor.poll() is None:vendor.kill()
                try:vendor.wait(timeout=3)
                except subprocess.TimeoutExpired:pass
                vendor.pc_reader.join(timeout=1);vendor.stdout.close()
            with self.lock:
                if self.vendor_process is vendor:self.vendor_process=None
                if self.process is provider:self.process=None
                self.value['monitoring']=False
    def close(self):
        self.closed.set()
        with self.lock:processes=[self.process,self.vendor_process]
        for p in processes:
            if p and p.poll() is None:
                try:p.kill()
                except OSError:pass
    def inspect(self,kind):
        if kind not in ('events','sleep'):raise ValueError('Неизвестная проверка')
        if self.app.demo:
            if kind=='events':return {'kind':kind,'demo':True,'events':[{'id':1000,'source':'Application Error · пример','time':'2026-10-19T07:20:00Z','message':'Пример: приложение завершилось с ошибкой. Совпадение по времени с обновлением само по себе не доказывает причину.'}]}
            return {'kind':kind,'demo':True,'checks':[{'title':'Последнее пробуждение','text':'Пример: USB-мышь'},{'title':'Что удерживает от сна','text':'Пример: проигрыватель видео'},{'title':'Таймеры пробуждения','text':'Пример: активных таймеров нет'}]}
        if kind=='events':
            result=self.app.backend.psjson(EVENTS_PS,timeout=20)
            if not isinstance(result,dict) or not isinstance(result.get('events'),list):raise ValueError('Windows не предоставила журнал')
            return {'kind':kind,'events':result['events'][:30]}
        checks=[]
        for title,flag in [('Последнее пробуждение','/lastwake'),('Что удерживает от сна','/requests'),('Таймеры пробуждения','/waketimers')]:
            try:text=self.app.backend.run([str(Path(os.environ.get('SystemRoot','C:\\Windows'))/'System32/powercfg.exe'),flag],timeout=10)
            except Exception:text='Windows не предоставила сведения. Для части проверок нужны права администратора.'
            checks.append({'title':title,'text':text[:4000]})
        return {'kind':kind,'checks':checks}
