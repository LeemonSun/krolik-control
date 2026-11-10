"""Windows probes and narrow repairs. Missing counters remain unknown."""
import base64
import ctypes
import ipaddress
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import time
import urllib.request
from .care import Cancelled,finding,audio_findings,network_findings,performance_findings

AUDIO_PS=r'''
$services=@(Get-Service -Name Audiosrv,AudioEndpointBuilder -ErrorAction SilentlyContinue|ForEach-Object{@{name=$_.Name;status=[string]$_.Status}})
$path='HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
$desktop=(Get-ItemProperty -LiteralPath ($path+'\NonPackaged') -ErrorAction SilentlyContinue).Value
$policy=(Get-ItemProperty -LiteralPath 'HKLM:\Software\Policies\Microsoft\Windows\AppPrivacy' -Name LetAppsAccessMicrophone -ErrorAction SilentlyContinue).LetAppsAccessMicrophone
$access=(Get-ItemProperty -LiteralPath $path -ErrorAction SilentlyContinue).Value
$drivers=@(Get-CimInstance Win32_PnPEntity -Filter "PNPClass='MEDIA' OR PNPClass='AudioEndpoint'" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue|Where-Object {$_.ConfigManagerErrorCode -ne 0}|ForEach-Object{@{name=$_.Name;problem=[int]$_.ConfigManagerErrorCode}})
@{services=$services;microphone_access=$access;microphone_desktop_access=$desktop;microphone_policy=$policy;drivers=$drivers}|ConvertTo-Json -Depth 5 -Compress
'''
NETWORK_PS=r'''
$rows=@(Get-NetIPConfiguration|ForEach-Object{$a=$_.NetAdapter;$ip=Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue;@{id=$_.InterfaceIndex;guid=[string]$a.InterfaceGuid;name=$_.InterfaceAlias;up=($a.Status -eq 'Up');dhcp=([string]$ip.Dhcp -eq 'Enabled');ipv4=@($_.IPv4Address.IPAddress);gateway=@($_.IPv4DefaultGateway.NextHop);dns=@($_.DNSServer.ServerAddresses)}})
$dns=$false
try{$q=[Net.Dns]::GetHostAddressesAsync('www.microsoft.com');if($q.Wait(3000)){$dns=($q.Result.Count -gt 0)}}catch{}
@{adapters=$rows;dns=$dns}|ConvertTo-Json -Depth 6 -Compress
'''
PERF_PS=r'''
$cpu=Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
$mem=Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 3 -ErrorAction Stop
$disk=Get-CimInstance Win32_PerfRawData_PerfDisk_PhysicalDisk -Filter "Name='_Total'" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
$gpu=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -OperationTimeoutSec 3 -ErrorAction SilentlyContinue|Where-Object {$_.Name -match 'engtype_3D'}
$byEngine=@{}
foreach($g in $gpu){$key=$g.Name -replace '^pid_\d+_','';if(!$byEngine.ContainsKey($key)){$byEngine[$key]=0.0};$byEngine[$key]+=[double]$g.UtilizationPercentage}
$gpuValue=$null;if($byEngine.Count -gt 0){$gpuValue=[Math]::Min(100,($byEngine.Values|Measure-Object -Maximum).Maximum)}
$cpuTotal=$null;$core=$null;if($cpu){$cpuTotal=($cpu|Where-Object Name -eq '_Total').PercentProcessorTime;$core=($cpu|Where-Object Name -ne '_Total'|Measure-Object PercentProcessorTime -Maximum).Maximum}
$latency=$null;if($disk -and $script:previousDisk){$operations=[double]$disk.AvgDisksecPerTransfer_Base-[double]$script:previousDisk.AvgDisksecPerTransfer_Base;$ticks=[double]$disk.AvgDisksecPerTransfer-[double]$script:previousDisk.AvgDisksecPerTransfer;if($operations -gt 0 -and $ticks -ge 0 -and $disk.Frequency_PerfTime -gt 0){$latency=1000*$ticks/[double]$disk.Frequency_PerfTime/$operations}};$script:previousDisk=$disk
$logical=[Environment]::ProcessorCount;$cpuProcesses=@(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -OperationTimeoutSec 3 -ErrorAction SilentlyContinue|Where-Object {$_.Name -notin @('Idle','_Total')}|Sort-Object PercentProcessorTime -Descending|Select-Object -First 5|ForEach-Object{@{name=$_.Name;pid=$_.IDProcess;cpu_percent=[Math]::Round([double]$_.PercentProcessorTime/$logical,1)}})
$processes=@(Get-Process -ErrorAction SilentlyContinue|Sort-Object WorkingSet64 -Descending|Select-Object -First 6|ForEach-Object{@{name=$_.ProcessName;pid=$_.Id;memory_mb=[Math]::Round($_.WorkingSet64/1MB)}})
@{cpu=$cpuTotal;cpu_core=$core;gpu=$gpuValue;ram_percent=[Math]::Round(100*(1-$mem.FreePhysicalMemory/$mem.TotalVisibleMemorySize),1);available_mb=[Math]::Round($mem.FreePhysicalMemory/1024);disk_ms=$latency;processes=$processes;cpu_processes=$cpuProcesses;time=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()}|ConvertTo-Json -Depth 5 -Compress
'''

def check(c):
    if c.cancel.is_set():raise Cancelled()

def powershell(c,script,data=None,timeout=60,stream=False):
    """Own the process so cancellation never terminates unrelated application work."""
    if os.name!='nt':raise RuntimeError('Доступно только в Windows')
    payload=base64.b64encode(json.dumps(data or {}).encode()).decode()
    prefix="$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$WarningPreference='SilentlyContinue';$InformationPreference='SilentlyContinue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$p=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+payload+"'))|ConvertFrom-Json);\n"
    encoded=base64.b64encode((prefix+script).encode('utf-16-le')).decode()
    executable=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    process=subprocess.Popen([executable,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],stdout=subprocess.PIPE,stderr=subprocess.STDOUT if stream else subprocess.PIPE,creationflags=0x08000000)
    with c.lock:c.process=process
    deadline=time.monotonic()+timeout
    try:
        if stream:
            lines=queue.Queue()
            def pump():
                try:
                    for line in process.stdout:lines.put(line)
                finally:lines.put(None)
            worker=__import__('threading').Thread(target=pump,daemon=True);worker.start();out=b'';err=b''
            while True:
                check(c)
                if time.monotonic()>deadline:raise TimeoutError('Время наблюдения истекло')
                try:line=lines.get(timeout=.2)
                except queue.Empty:continue
                if line is None:break
                try:stream(json.loads(line.decode('utf-8-sig')))
                except json.JSONDecodeError:err+=line
            process.wait(timeout=3)
        else:
            while True:
                check(c)
                try:out,err=process.communicate(timeout=.2);break
                except subprocess.TimeoutExpired:
                    if time.monotonic()>deadline:raise TimeoutError('Проверка Windows превысила время ожидания')
        if process.returncode:raise RuntimeError(err.decode('utf-8',errors='replace')[-5000:])
        return out.decode('utf-8-sig').strip()
    finally:
        if process.poll() is None:process.kill();process.communicate()
        with c.lock:c.process=None

def psjson(c,script,data=None,timeout=60):
    raw=powershell(c,script,data,timeout)
    return json.loads(raw) if raw else {}

def audio_probe(c):
    from .audio import enumerate_audio,audio_sessions
    try:result=psjson(c,AUDIO_PS,timeout=25)
    except (OSError,RuntimeError,TimeoutError,ValueError) as exc:result={'probe_error':str(exc)}
    try:result['endpoints']=enumerate_audio()
    except OSError as exc:result['endpoints']=[];result['audio_error']=str(exc)
    try:result['sessions']=audio_sessions()
    except OSError:result['sessions']=[];result['sessions_unavailable']=True
    return result

def network_probe(c):
    try:raw=psjson(c,NETWORK_PS,timeout=20)
    except (OSError,RuntimeError,TimeoutError,ValueError) as exc:raw={'adapters':[],'dns':None,'adapters_unknown':True,'probe_error':str(exc)}
    try:
        with urllib.request.urlopen('https://www.microsoft.com/',timeout=4) as response:raw['https']=200<=response.status<400
    except Exception:raw['https']=False
    check(c)
    gateways=[g for a in raw['adapters'] if a['up'] for g in a['gateway']]
    targets=[]
    for label,host in [('роутер',gateways[0] if gateways else None),('внешний узел','1.1.1.1')]:
        if not host:continue
        try:ipaddress.ip_address(host)
        except ValueError:continue
        targets.append({'label':label,'host':host})
    try:raw['pings']=psjson(c,r'''
@($p.targets|ForEach-Object{$x=$_;$ping=[Net.NetworkInformation.Ping]::new();$times=@();try{1..5|ForEach-Object{try{$r=$ping.Send($x.host,700);if($r.Status -eq 'Success'){$times+=([double]$r.RoundtripTime)}}catch{}}}finally{$ping.Dispose()};@{label=$x.label;sent=5;received=$times.Count;average_ms=if($times.Count){[Math]::Round(($times|Measure-Object -Average).Average,1)}else{$null}}})|ConvertTo-Json -Depth 4 -Compress
''',{'targets':targets},timeout=15)
    except (OSError,RuntimeError,TimeoutError,ValueError) as exc:raw['pings']=[];raw['ping_error']=str(exc)
    if isinstance(raw['pings'],dict):raw['pings']=[raw['pings']]
    return raw

def observe(c,seconds):
    c.stage('Собираем исходные показатели');samples=[]
    def sample(row):
        samples.append(row)
        with c.lock:c.state['live']=row
        c.stage('Наблюдение · '+str(round(row['elapsed']))+' / '+str(seconds)+' с')
    script='function Snapshot {\n'+PERF_PS+"\n}\n$null=Snapshot;Start-Sleep -Seconds 1;$count=0;$watch=[Diagnostics.Stopwatch]::StartNew();do{$row=Snapshot|ConvertFrom-Json;$row|Add-Member elapsed ([Math]::Round($watch.Elapsed.TotalSeconds,1));$row|ConvertTo-Json -Depth 6 -Compress;$count++;Start-Sleep -Seconds 1}while($watch.Elapsed.TotalSeconds -lt $p.seconds -or $watch.Elapsed.TotalSeconds -lt 30 -and $count -lt 3)"
    powershell(c,script,{'seconds':seconds},timeout=seconds+90,stream=sample)
    return {'title':'Нагрузка за '+str(seconds)+' секунд','samples':samples,'findings':performance_findings(samples),'note':'Общесистемные счётчики. Без захвата FPS, температур и содержимого игры.'}

def speed_test(c,factory=None):
    import http.client
    import threading
    factory=factory or http.client.HTTPSConnection
    primary=factory('speed.cloudflare.com',timeout=8);meter=factory('speed.cloudflare.com',timeout=4)
    stop=threading.Event();worker=None;idle=[];loaded=[];size=24*1024*1024;count=0
    def latency(connection):
        check(c);start=time.perf_counter()
        connection.request('GET','/__down?bytes=0&nonce='+secrets.token_hex(4),headers={'Cache-Control':'no-cache','Accept-Encoding':'identity'})
        response=connection.getresponse()
        if response.status!=200:raise OSError('Сервер измерений вернул HTTP '+str(response.status))
        response.read(1024)
        return round((time.perf_counter()-start)*1000,1)
    try:
        c.stage('Проверяем сервер измерений')
        primary.connect();meter.connect() # TLS/DNS setup is outside the timing window.
        c.stage('Задержка до проверочного HTTPS-узла')
        for _ in range(4):idle.append(latency(primary))
        def sample_latency():
            while not stop.wait(.4):
                try:loaded.append(latency(meter))
                except Exception:return
        worker=threading.Thread(target=sample_latency,daemon=True);worker.start()
        c.stage('Измеряем скачивание · до 24 МБ')
        primary.request('GET','/__down?bytes='+str(size)+'&nonce='+secrets.token_hex(4),headers={'Cache-Control':'no-cache','Accept-Encoding':'identity'})
        response=primary.getresponse()
        if response.status!=200:raise OSError('Скачивание: HTTP '+str(response.status))
        start=time.perf_counter();deadline=time.monotonic()+30
        while True:
            check(c)
            if time.monotonic()>deadline:raise TimeoutError('Скачивание превысило 30 секунд')
            block=response.read(65536)
            if not block:break
            count+=len(block)
            if count>size:raise ValueError('Сервер прислал неожиданный объём')
        elapsed=time.perf_counter()-start
        if count!=size or elapsed<=0:raise ValueError('Получен неполный результат измерения')
        down=count*8/elapsed/1e6
        stop.set();worker.join(timeout=5)
        c.stage('Измеряем отдачу · 4 МБ')
        data=os.urandom(4*1024*1024);check(c);start=time.perf_counter()
        primary.request('POST','/__up',body=data,headers={'Content-Type':'application/octet-stream','Accept-Encoding':'identity'})
        response=primary.getresponse()
        if not 200<=response.status<300:raise OSError('Отдача: HTTP '+str(response.status))
        response.read(65536);upload_elapsed=time.perf_counter()-start
        up=len(data)*8/upload_elapsed/1e6
        avg=lambda v:round(sum(v)/len(v),1) if v else None
        jitter=avg([abs(b-a) for a,b in zip(idle,idle[1:])])
        findings=[finding('speed_scope','Измерена связь с Cloudflare','Короткий тест одного маршрута. Он не является окончательной оценкой тарифа. HTTP-задержка отличается от ICMP ping. При недостатке отсчётов задержка под нагрузкой остаётся недоступной.','info')]
        if elapsed<.25:findings.append(finding('short_transfer','Скачивание закончилось очень быстро','Для высокой скорости 24 МиБ могут быть недостаточны для устойчивого измерения. Значение ориентировочное.','info'))
        return {'title':'Короткий тест интернет-соединения','metrics':{'download_mbps':round(down,1),'upload_mbps':round(up,1),'latency_ms':avg(idle),'jitter_ms':jitter,'loaded_latency_ms':avg(loaded),'transferred_mb':round((count+len(data))/1024/1024,1)},'findings':findings}
    finally:
        stop.set();primary.close();meter.close()
        if worker:worker.join(timeout=5)


def driver_root():
    if os.name!='nt':return Path.home()/'Documents/Krolik Control/Driver Backups'
    from .audio import guid,GUID,LONG,DWORD
    C=ctypes;shell=C.WinDLL('shell32');ole=C.OleDLL('ole32');ptr=C.c_void_p();ident=guid('FDD39AD0-238F-46AF-ADB4-6C85480369C7')
    shell.SHGetKnownFolderPath.argtypes=[C.POINTER(GUID),DWORD,C.c_void_p,C.POINTER(C.c_void_p)];shell.SHGetKnownFolderPath.restype=LONG;ole.CoTaskMemFree.argtypes=[C.c_void_p]
    if shell.SHGetKnownFolderPath(C.byref(ident),0,None,C.byref(ptr))<0:raise OSError('Не удалось найти папку Документы')
    try:return Path(C.wstring_at(ptr))/'Krolik Control/Driver Backups'
    finally:ole.CoTaskMemFree(ptr)


def run(c,kind,body):
    if kind=='audio':c.stage('Устройства, службы и отдельные приложения');raw=audio_probe(c);return {'title':'Диагностика звука и микрофона','raw':raw,'findings':audio_findings(raw)}
    if kind=='network':c.stage('Адаптеры, DNS, HTTPS и ответы роутера');raw=network_probe(c);return {'title':'Диагностика подключения','raw':raw,'findings':network_findings(raw)}
    if kind in ('system','observe'):return observe(c,body.get('seconds',30) if kind=='observe' else 6)
    if kind=='speed':return speed_test(c)
    if kind=='game':
        from .game_capture import run as capture_game
        return capture_game(c,body)
    if kind=='memory':
        from .memory_test import run as test_memory
        return test_memory(c,body)
    if kind=='benchmark':
        from .benchmarks import run_benchmarks
        return run_benchmarks(c)
    if kind=='voice':
        from .audio_tools import record_voice,voice_metrics
        c.stage('Говорите 5 секунд; затем сделайте паузу на 1 секунду')
        recording=record_voice(body['id'],c.cancel,c.stage)
        c.voice=recording
        metrics=voice_metrics(recording);findings=[finding('voice','Запись готова к прослушиванию','Звук хранится только в памяти до следующей записи или закрытия программы. Оценка шума предполагает паузу в последнюю секунду.','info')]
        if metrics['peak_dbfs']<-60:findings.append(finding('no_signal','Сигнал отсутствует или очень тихий','Проверьте выбранный микрофон, его громкость и подключение. Одна тихая запись не доказывает поломку.','warning'))
        if metrics['clipping_percent']>.1:findings.append(finding('clipping','Обнаружен перегруз сигнала','Уменьшите усиление или отодвиньтесь от микрофона, затем сравните повторную запись.','warning'))
        if metrics['pause_rms_dbfs']>-35:findings.append(finding('noise','В последнюю секунду был заметный сигнал','Если вы молчали, это может быть фон или шум. Если говорили — повторите тест с паузой.','warning'))
        return {'title':'Проверка микрофона','metrics':metrics,'findings':findings}
    if kind in ('integrity','repair_system'):
        repair=kind=='repair_system';c.stage('Восстановление Windows' if repair else 'Проверка хранилища компонентов Windows')
        raw=psjson(c,r"$r=if($p.repair){Repair-WindowsImage -Online -RestoreHealth -NoRestart -ErrorAction Stop}else{Repair-WindowsImage -Online -ScanHealth -NoRestart -ErrorAction Stop};@{health=[string]$r.ImageHealthState;restart=[bool]$r.RestartNeeded}|ConvertTo-Json -Compress",{'repair':repair},timeout=1200)
        health=raw.get('health');title={'Healthy':'Хранилище компонентов исправно','Repairable':'Найдены повреждения, доступные для восстановления','NonRepairable':'Windows сообщает о невосстановимых повреждениях'}.get(health,'Windows вернула неопределённый результат')
        return {'title':'Восстановление компонентов Windows' if repair else 'Проверка компонентов Windows','raw':raw,'findings':[finding('dism',title,'Проверяется хранилище компонентов Windows. Это не проверка всех файлов диска и не проверка на вирусы.','ok' if health=='Healthy' else 'warning')],'reboot':raw.get('restart',False)}
    if kind=='driver_backup':
        from .driver_safety import create
        c.stage('Сохраняем и проверяем сторонние пакеты драйверов')
        r=create(c.app.backend,automatic=False)
        return {'title':'Резервная копия драйверов','backup':Path(r['path']).name,'raw':r,'findings':[finding('backup','Сохранено пакетов: '+str(r['packages']),'Целостность файлов записана. Скопируйте папку на флешку; встроенные пакеты Windows и фирменные панели не входят.','ok')]}
    if kind=='driver_restore':
        name=body.get('backup','')
        if not isinstance(name,str) or Path(name).name!=name or not name.startswith('Drivers-'):raise ValueError('Выберите сохранённую копию')
        dest=(driver_root()/name).resolve()
        if dest.parent!=driver_root().resolve() or not (dest/'KrolikControl-backup.json').is_file():raise ValueError('Копия не найдена')
        for base,dirs,files in os.walk(dest):
            if any((Path(base)/name).is_symlink() or getattr(os.path,'isjunction',lambda p:False)(Path(base)/name) for name in [*dirs,*files]):raise ValueError('Копия содержит ссылки за пределы папки')
        from .driver_safety import verify_manifest
        verify_manifest(dest)
        if not list(dest.rglob('*.inf')):raise ValueError('В копии нет INF-пакетов')
        c.stage('Windows выбирает подходящие подписанные драйверы')
        raw=psjson(c,r'''$text=& (Join-Path $env:SystemRoot 'System32\pnputil.exe') /add-driver (Join-Path $p.path '*.inf') /subdirs /install 2>&1|Out-String;@{code=$LASTEXITCODE;text=$text}|ConvertTo-Json -Compress''',{'path':str(dest)},timeout=600)
        return {'title':'Восстановление драйверов','raw':raw,'reboot':raw['code']==3010,'findings':[finding('restored','Обработка пакетов завершена' if raw['code'] in (0,3010) else 'Windows вернула ошибку','Код '+str(raw['code'])+'. Windows применяет только подходящие пакеты по своему ранжированию. Количество реально заменённых драйверов смотрите в подробностях.','info' if raw['code'] in (0,3010) else 'warning')]}
    raise ValueError('Неизвестная операция')

def repair(c,row):
    action=row['action'];target=row.get('target');c.stage('Повторно проверяем причину перед исправлением')
    if action=='audio_service':
        if target not in ('Audiosrv','AudioEndpointBuilder'):raise ValueError('Неизвестная служба')
        psjson(c,r'''$s=Get-Service -Name $p.name;if($s.Status -ne 'Stopped'){throw 'Состояние изменилось; повторите диагностику'};Start-Service -Name $p.name -ErrorAction Stop;(Get-Service -Name $p.name).WaitForStatus('Running',[TimeSpan]::FromSeconds(10));@{running=$true}|ConvertTo-Json''',{'name':target},timeout=20)
        raw=audio_probe(c);return {'title':'Служба запущена; выполнена повторная диагностика','raw':raw,'findings':audio_findings(raw)}
    if action=='dns_flush':
        before=network_probe(c)
        if before.get('dns') is not False:raise ValueError('Проблема уже не воспроизводится. Настройки не менялись.')
        powershell(c,"Clear-DnsClientCache -ErrorAction Stop",timeout=10)
        raw=network_probe(c);return {'title':'DNS-кэш очищен; выполнена повторная проверка','raw':raw,'findings':network_findings(raw)}
    if action=='dhcp_renew':
        raw=network_probe(c);adapter=next((a for a in raw['adapters'] if a['guid']==target and a['up'] and a['dhcp'] and any(isinstance(ip,str) and ip.startswith('169.254.') for ip in a['ipv4'])),None)
        if not adapter:raise ValueError('Состояние адаптера изменилось; повторите диагностику')
        powershell(c,r'''$a=Get-CimInstance Win32_NetworkAdapterConfiguration|Where-Object {$_.SettingID -eq $p.guid -and $_.DHCPEnabled};if(@($a).Count -ne 1){throw 'Адаптер изменился'};$r=Invoke-CimMethod -InputObject $a -MethodName RenewDHCPLease;if($r.ReturnValue -ne 0){throw ('DHCP code '+$r.ReturnValue)}''',{'guid':target},timeout=30)
        raw=network_probe(c);return {'title':'Адрес запрошен повторно','raw':raw,'findings':network_findings(raw)}
    if action=='mic_access':
        raw=audio_probe(c)
        if raw.get('microphone_policy')==2:raise ValueError('Микрофон запрещён политикой организации; изменение не выполнялось')
        if raw.get('microphone_access')!='Deny':raise ValueError('Разрешение изменилось; повторите диагностику')
        from .workspace import atomic_json
        atomic_json(c.directory/'last-repair-undo.json',{'kind':'mic_access','previous':'Deny','report':c.active_repair})
        psjson(c,r'''$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone';if((Get-ItemProperty $key).Value -ne 'Deny'){throw 'Разрешение изменилось'};Set-ItemProperty -LiteralPath $key -Name Value -Value 'Allow';@{value=(Get-ItemProperty $key).Value}|ConvertTo-Json''',timeout=10)
        raw=audio_probe(c)
        if raw.get('microphone_access')!='Allow':raise RuntimeError('Windows не подтвердила разрешение')
        c.undo={'kind':'mic_access','previous':'Deny','report':c.active_repair}
        from .workspace import atomic_json
        atomic_json(c.directory/'last-repair-undo.json',c.undo)
        return {'title':'Разрешение микрофона включено','raw':raw,'findings':audio_findings(raw),'undo':'mic_access'}
    if action=='session_unmute':
        from .audio import set_session,audio_sessions
        current=next((r for r in audio_sessions() if r['id']==target),None)
        if not current or not (current['mute'] or current['volume']==0):raise ValueError('Сессия изменилась. Повторите диагностику')
        from .workspace import atomic_json
        atomic_json(c.directory/'last-repair-undo.json',{'kind':'session','report':c.active_repair,'target':target,'mute':current['mute'],'volume':current['volume'],'applied':70 if current['volume']==0 else current['volume']})
        set_session(target,False,70 if current['volume']==0 else current['volume'])
        raw=audio_probe(c);return {'title':'Звук приложения включён; проверка повторена','raw':raw,'findings':audio_findings(raw),'undo':'session'}
    raise ValueError('Недоступное исправление')

def demo_run(c,kind,body):
    c.stage('Демонстрация · '+kind);time.sleep(.08)
    if kind=='audio':
        raw={'endpoints':[{'id':'demo-output','name':'Динамики','flow':0,'controllable':True,'volume':0,'mute':True},{'id':'demo-microphone','name':'Микрофон','flow':1,'volume':70,'mute':False}],'services':[],'sessions':[]};return {'title':'Диагностика звука · пример','raw':raw,'findings':audio_findings(raw)}
    if kind=='network':
        raw={'adapters':[{'up':True,'dhcp':True,'name':'Ethernet','guid':'demo-adapter','ipv4':['169.254.1.2']}],'dns':False,'https':False,'pings':[]};return {'title':'Подключение · пример','raw':raw,'findings':network_findings(raw)}
    if kind in ('system','observe'):
        samples=[{'elapsed':i*2,'cpu':45+i,'cpu_core':98,'gpu':78,'ram_percent':93,'disk_ms':4,'processes':[{'name':'Пример игры','memory_mb':14000}]} for i in range(8)];return {'title':'Нагрузка · пример','samples':samples,'findings':performance_findings(samples)}
    if kind=='speed':return {'title':'Скорость · пример','metrics':{'download_mbps':320,'upload_mbps':280,'latency_ms':18,'jitter_ms':3,'loaded_latency_ms':70,'transferred_mb':0},'findings':[finding('demo','Демонстрационные данные','Сетевой тест не запускался.','info')]}
    if kind=='game':return {'title':'Игровая сессия · пример','metrics':{'present_fps':120,'frame_p95_ms':12.2,'frame_p99_ms':18.1,'slowest_percent_fps':48,'captured_frames':3600},'findings':[finding('demo_game','Пример измерения','Реальная игра и кадры не записывались.','info')]}
    if kind=='memory':return {'title':'Память · пример','metrics':{'tested_mb':body.get('mb',256),'duration_s':body.get('seconds',30),'rounds':12,'patterns':60,'errors':0},'findings':[finding('demo_memory','Пример результата','Реальная память не проверялась.','info')]}
    if kind=='benchmark':return {'title':'Бенчмарк · пример','metrics':{'cpu_single_mloops':82,'cpu_multi_mloops':710,'threads':16,'memory_mib_s':18000,'disk_write_mib_s':980,'disk_read_mib_s':1900,'gpu_ms':3.2,'gpu_name':'Демонстрационная видеокарта'},'findings':[finding('demo_bench','Пример результатов','Это не измерения вашего ПК.','info')]}
    if kind=='voice':return {'title':'Микрофон · пример','metrics':{'peak_dbfs':-8,'rms_dbfs':-22,'clipping_percent':0,'pause_rms_dbfs':-58},'findings':[finding('demo_voice','Демонстрация','Запись не выполнялась.','info')]}
    return {'title':'Демонстрация операции','findings':[finding('demo_action','Система не менялась','Реальные команды в демонстрации не выполняются.','info')]}
