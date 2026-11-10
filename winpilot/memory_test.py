"""Bounded native RAM verification; cancellation kills only this owned helper."""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from .care import Cancelled,finding

def options(body):
    mb=body.get('mb',256);seconds=body.get('seconds',30)
    if type(mb)!=int or mb not in (128,256,512,1024):raise ValueError('Выберите 128, 256, 512 или 1024 МиБ')
    if type(seconds)!=int or seconds not in (30,120,300):raise ValueError('Выберите 30, 120 или 300 секунд')
    return mb,seconds

def interpret(row):
    if not isinstance(row,dict) or any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) or row[k]<0 for k in ('tested_mb','duration_s','rounds','patterns','errors')):raise ValueError('Неполный результат проверки памяти')
    if row['errors']:
        return [finding('memory_data_error','Проверка прочитала изменившиеся данные','Обнаружено несовпадений: '+str(row['errors'])+'. Остановите разгон и повторите проверку. Причиной могут быть RAM, контроллер, процессор или другая нестабильность; конкретный компонент этим тестом не установлен.','problem')]
    if row.get('memory_pressure') or row['rounds']<1:return [finding('memory_incomplete','Полный цикл не завершён','Не хватает доступной памяти либо тест остановлен до полного цикла. Результат не считается успешной проверкой.','warning')]
    return [finding('memory_no_errors','В проверенном объёме несовпадений не найдено','Проверено '+str(row['tested_mb'])+' МиБ в пользовательском процессе. Системная и недоступная память не проверяются. Короткий запуск не доказывает стабильность всего ПК.','ok')]

def run(c,body):
    mb,seconds=options(body);helper=Path(__file__).resolve().parents[1]/'krolik-memory.exe'
    if not helper.is_file():raise RuntimeError('Модуль проверки памяти отсутствует. Используйте полную Windows-сборку.')
    p=subprocess.Popen([str(helper),'--mb',str(mb),'--seconds',str(seconds)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000 if os.name=='nt' else 0)
    with c.lock:c.process=p
    lines=queue.Queue(maxsize=64)
    def pump():
        for line in p.stdout:
            if len(line)>8192:continue
            try:row=json.loads(line)
            except (ValueError,UnicodeError):continue
            try:lines.put_nowait(row)
            except queue.Full:pass
    reader=threading.Thread(target=pump,daemon=True);reader.start();result=None;deadline=time.monotonic()+seconds+60
    try:
        while p.poll() is None or reader.is_alive() or not lines.empty():
            if c.cancel.is_set():raise Cancelled()
            if time.monotonic()>deadline:raise TimeoutError('Проверка памяти остановлена по ограничению времени')
            try:row=lines.get(timeout=.15)
            except queue.Empty:continue
            if row.get('phase')=='result':result=row
            elif row.get('phase')=='progress':c.stage('Память · '+str(row.get('mb','—'))+' МиБ · '+str(round(row.get('elapsed',0)))+' / '+str(seconds)+' с · проверок: '+str(row.get('patterns',0)))
        if p.returncode==3:raise ValueError('Недостаточно свободной памяти. Закройте тяжёлые программы и повторите.')
        if p.returncode not in (0,1,4) or result is None:raise RuntimeError('Проверка памяти не вернула полный результат')
        if p.returncode==1 and not result.get('errors'):raise RuntimeError('Несогласованный результат проверки памяти')
        findings=interpret(result)
        return {'title':'Проверка данных оперативной памяти','workload':'kc-memory-1','metrics':{k:result[k] for k in ('tested_mb','duration_s','rounds','patterns','errors')},'findings':findings,'note':'kc-memory-1: нули, единицы, чередование битов, шаблон от адреса/цикла и бегущая единица. Проверяется выделенный объём процесса; это не полное сканирование физических адресов.'}
    finally:
        if p.poll() is None:p.kill()
        p.wait(timeout=5);reader.join(timeout=2);p.stdout.close();p.stderr.close()
        with c.lock:c.process=None
