"""Bounded per-process PresentMon capture. No injection, screenshots or input logging."""
import csv
import hashlib
import math
import os
from pathlib import Path
import secrets
import statistics
import subprocess
import time
from types import SimpleNamespace
from .care import Cancelled,finding,performance_findings

PRESENTMON_SHA='b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af'
PROCESSES_PS=r'''@(Get-Process -ErrorAction SilentlyContinue|Where-Object {$_.MainWindowHandle -ne 0 -and $_.Id -ne $PID}|Select-Object -First 128|ForEach-Object{try{@{id=$_.Id;name=$_.ProcessName;started=$_.StartTime.ToUniversalTime().ToString('o')}}catch{}})|ConvertTo-Json -Depth 4 -Compress'''

def parse_capture(path,pid):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>64*1024**2:raise ValueError('Файл измерений отсутствует или слишком большой')
    groups={}
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        required={'ProcessID','SwapChainAddress','msBetweenPresents'}
        if not required.issubset(set(reader.fieldnames or [])):raise ValueError('Формат измерений PresentMon не поддерживается')
        for i,row in enumerate(reader):
            if i>=1_000_000:raise ValueError('Слишком много кадров для короткого теста')
            if row.get('ProcessID')!=str(pid):continue
            try:value=float(row['msBetweenPresents']);stamp=float(row.get('TimeInSeconds','nan'))
            except (ValueError,TypeError):continue
            if not math.isfinite(value) or not 0<value<=60000:continue
            group=row.get('SwapChainAddress','')[:80]
            if len(groups)>=128 and group not in groups:continue
            groups.setdefault(group,[]).append((value,stamp if math.isfinite(stamp) else None))
    if not groups:raise ValueError('Кадры выбранного процесса не найдены. Запустите игру и повторите.')
    group,values=max(groups.items(),key=lambda x:len(x[1]));times=sorted(x[0] for x in values)
    if len(times)<30:raise ValueError('Слишком мало кадров для сравнения. Повторите во время игры.')
    mean=statistics.fmean(times);slow=times[-max(1,math.ceil(len(times)*.01)):]
    at=lambda q:times[min(len(times)-1,math.ceil(q*len(times))-1)]
    first=next((t for _,t in values if t is not None),None);bins={}
    if first is not None:
        for value,stamp in values:
            if stamp is None:continue
            second=int(stamp-first)
            if 0<=second<300:bins.setdefault(second,[]).append(value)
    return {'metrics':{'present_fps':round(1000/mean,1),'frame_p95_ms':round(at(.95),2),'frame_p99_ms':round(at(.99),2),'slowest_percent_fps':round(1000/statistics.fmean(slow),1),'captured_frames':len(times)},'frames':[{'elapsed':k,'frame_ms':round(statistics.fmean(v),2),'present_fps':round(1000/statistics.fmean(v),1)} for k,v in sorted(bins.items())],'swapchains':len(groups),'selected_swapchain':group}

def options(c,body):
    pid=body.get('pid');seconds=body.get('seconds',30)
    if type(pid)!=int or pid<=0 or pid>2**32-1 or seconds not in (30,60) or type(seconds)!=int:raise ValueError('Выберите процесс и 30 или 60 секунд')
    known=c.app.data.get('game_processes',[])
    row=next((r for r in known if r['id']==pid),None)
    if not row:raise ValueError('Обновите список запущенных приложений')
    return pid,seconds,row

def run(c,body):
    pid,seconds,row=options(c,body)
    helper=Path(__file__).resolve().parents[1]/'PresentMon-2.6.0-x64.exe'
    if not helper.is_file() or hashlib.sha256(helper.read_bytes()).hexdigest()!=PRESENTMON_SHA:raise ValueError('Модуль измерения кадров отсутствует или изменён')
    check=c.app.backend.psjson("$g=Get-Process -Id $p.pid -ErrorAction Stop;@{name=$g.ProcessName;started=$g.StartTime.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress",{'pid':pid},timeout=10)
    if check.get('started')!=row['started'] or check.get('name')!=row['name']:raise ValueError('Выбранный процесс завершился или был заменён. Обновите список.')
    path=c.directory/('frames-'+secrets.token_hex(12)+'.csv');session='Krolik-'+secrets.token_hex(12)
    args=[str(helper),'--process_id',str(pid),'--delay','3','--timed',str(seconds),'--terminate_after_timed','--terminate_on_proc_exit','--output_file',str(path),'--session_name',session,'--no_console_stats','--no_track_input','--v1_metrics']
    from .pc import PcCenter
    wrapper=SimpleNamespace(demo=False,backend=c.app.backend,engine=c.app.engine,care=SimpleNamespace(state={'running':False}),lock=c.app.lock,info=c.app.info,data_revision=0)
    sensors=PcCenter(wrapper);sensors.value['hardware_status']='done';samples=[];started=time.monotonic();last=-3
    try:process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000 if os.name=='nt' else 0)
    except BaseException:sensors.close();raise
    with c.lock:c.process=process
    try:
        while process.poll() is None:
            if c.cancel.is_set():raise Cancelled()
            elapsed=time.monotonic()-started
            if elapsed>seconds+20:raise TimeoutError('Измерение кадров превысило ограничение времени')
            if elapsed-last>=2:
                d=sensors.read();live=d.get('live')
                if live:samples.append({'elapsed':round(elapsed,1),**live})
                last=elapsed;c.stage('Запись игры · '+str(round(elapsed))+' / '+str(seconds)+' с · '+row['name'])
            c.cancel.wait(.2)
        if c.cancel.is_set():raise Cancelled()
        if process.returncode:raise ValueError('PresentMon не завершил запись. Проверьте права администратора и поддержку игры.')
        data=parse_capture(path,pid)
        findings=[finding('frames','Кадры выбранного приложения записаны','Измерены интервалы отправки кадров PresentMon. Это не время отклика монитора. Для нескольких цепочек выбрана цепочка с наибольшим числом кадров.','info')]
        if data['metrics']['frame_p99_ms']>50:findings.append(finding('frame_spikes','В выборке есть длинные интервалы кадров','99-й процентиль больше 50 мс. Загрузка сцены, фоновые задачи и ограничения игры могут влиять; аппаратная причина по одному числу не установлена.','warning'))
        findings+=performance_findings(samples)
        return {'title':'Игровая сессия · '+row['name'],'metrics':data['metrics'],'samples':samples,'frames':data['frames'],'findings':findings,'note':'PresentMon 2.6.0, v1 metrics. FPS = 1000 / средний msBetweenPresents; медленный 1% = 1000 / средний интервал худшего 1% кадров. Температуры и GPU доступны только при наличии соответствующих источников. Полный CSV удаляется после анализа.','raw':{'application':row['name'],'swapchains':data['swapchains'],'selected_swapchain':data['selected_swapchain']}}
    finally:
        forced=process.poll() is None
        if forced:process.kill()
        process.wait(timeout=5);sensors.close();path.unlink(missing_ok=True)
        # stop() may already have killed the process; its ETW session still needs cleanup.
        if forced or c.cancel.is_set() or process.returncode:
            try:subprocess.run([str(helper),'--session_name',session,'--terminate_existing_session'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,creationflags=0x08000000 if os.name=='nt' else 0)
            except (OSError,subprocess.TimeoutExpired):pass
        with c.lock:c.process=None
