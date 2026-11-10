"""Fixed-workload measurements. No fabricated cross-hardware rankings."""
import json
import math
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import time
from .care import Cancelled,finding

def interpret(metrics,previous=None):
    result=[finding('scope','Результаты для сравнения этого ПК','Сравнивайте повторные запуски при одинаковом питании и закрытых фоновых задачах. Короткий синтетический тест не доказывает причину просадок в конкретной игре.','info')]
    for key,label in [('cpu_single_mloops','CPU, один поток'),('cpu_multi_mloops','CPU, несколько потоков'),('memory_mib_s','Память'),('disk_read_mib_s','Чтение диска'),('disk_write_mib_s','Запись диска'),('gpu_ms','GPU')]:
        value=metrics.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:metrics[key]=None;result.append(finding('unsupported_'+key,label+': результат недоступен','Показатель не измерен. Это не означает неисправность.','info'))
        elif previous and (not key.startswith('disk_') or bool(metrics.get('disk_target')) and previous.get('disk_target')==metrics.get('disk_target')) and (key!='gpu_ms' or previous.get('gpu_name')==metrics.get('gpu_name')) and isinstance(previous.get(key),(int,float)) and previous[key]>0:
            ratio=previous[key]/value if key=='gpu_ms' else value/previous[key]
            if ratio<.7:result.append(finding('regression_'+key,label+': результат заметно хуже предыдущего','Изменение более 30%. Повторите в одинаковых условиях; влияют фоновые задачи, питание и нагрев. Причина пока не установлена.','warning'))
    return result

def run_benchmarks(c):
    helper=Path(__file__).resolve().parents[1]/'krolik-bench.exe'
    if not helper.is_file():raise RuntimeError('В этой сборке нет нативного модуля бенчмарка. Используйте Windows portable/Setup.')
    path=c.directory/('bench-'+secrets.token_hex(12)+'.tmp');c.stage('CPU → память → диск → GPU · короткие измерения')
    process=subprocess.Popen([str(helper),str(path)],cwd=c.directory,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000 if os.name=='nt' else 0)
    with c.lock:c.process=process
    deadline=time.monotonic()+120
    try:
        while True:
            if c.cancel.is_set():raise Cancelled()
            try:out,err=process.communicate(timeout=.2);break
            except subprocess.TimeoutExpired:
                if time.monotonic()>deadline:raise TimeoutError('Тест превысил две минуты и остановлен')
        if process.returncode:raise RuntimeError(err.decode('utf-8',errors='replace') or 'Бенчмарк завершился с ошибкой')
        metrics=json.loads(out.decode('utf-8'));metrics['disk_target']=str(c.directory.anchor);hardware=hashlib.sha256(json.dumps({k:(c.app.info or {}).get(k) for k in ('cpu','gpu','ram')},sort_keys=True).encode()).hexdigest();previous=next((r.get('metrics') for r in c.state['reports'] if r['kind']=='benchmark' and not r.get('demo') and r.get('workload')=='kc-bench-1' and r.get('hardware')==hardware),None)
        return {'title':'Базовая производительность','workload':'kc-bench-1','hardware':hardware,'note':'kc-bench-1: CPU xorshift single/multi; память: копирование 128 МиБ; диск: последовательные 256 МиБ с NO_BUFFERING/WRITE_THROUGH; GPU: compute D3D11, аппаратные timestamp/disjoint и readback.','metrics':metrics,'findings':interpret(metrics,previous)}
    finally:
        if process.poll() is None:process.kill();process.communicate()
        with c.lock:c.process=None
        path.unlink(missing_ok=True)
