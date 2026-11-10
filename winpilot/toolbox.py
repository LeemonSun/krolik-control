"""On-demand tools with owned helpers, bounded results and immutable file previews."""
import copy
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from .files import Stopped,check
from .workspace import atomic_json
from .power import PowerLease

PICKER_PS=r'''Add-Type -AssemblyName System.Windows.Forms;if($p.kind -eq 'folder'){$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='Выберите папку для Krolik Control';$d.ShowNewFolderButton=$false}else{$d=New-Object System.Windows.Forms.OpenFileDialog;$d.Title='Выберите файл для Krolik Control';$d.CheckFileExists=$true;$d.Multiselect=$false};try{if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){@{path=if($p.kind -eq 'folder'){$d.SelectedPath}else{$d.FileName}}|ConvertTo-Json -Compress}else{@{cancelled=$true}|ConvertTo-Json -Compress}}finally{$d.Dispose()}'''
KINDS={'pick_folder','pick_file','disk_map','duplicates','hash','file_locks','rename','rename_undo','processes','connections','network_chain','wifi','battery','security','drive_health','peripherals','printers','startup_extra','prepare_transfer','latency','crashes','rename_recover','offline_cache','rename_preview'}

def rows(v):return v if isinstance(v,list) else [v] if isinstance(v,dict) else []
def host_value(value):
    if not isinstance(value,str) or not 1<=len(value)<=253 or any(c in value for c in '/\\@?#\x00 \t\r\n'):raise ValueError('Введите только домен или IP-адрес')
    try:return str(ipaddress.ip_address(value))
    except ValueError:
        try:value=value.encode('idna').decode('ascii')
        except UnicodeError:raise ValueError('Домен не распознан') from None
        # A rejected dotted IPv4 address must not fall through as a DNS name.
        if re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}\.?',value):raise ValueError('Введите только домен или IP-адрес')
        if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',p) for p in value.rstrip('.').split('.')):raise ValueError('Домен не распознан')
        if len(value)>253:raise ValueError('Домен слишком длинный')
        return value

def valid_report(r):
    if not isinstance(r,dict) or not isinstance(r.get('kind'),str) or r['kind'] not in KINDS or not isinstance(r.get('title'),str) or not 1<=len(r['title'])<=300 or type(r.get('time')) not in (int,float) or not math.isfinite(r['time']) or not 0<=r['time']<=32503680000:return False
    json.dumps(r,allow_nan=False)
    for k in ('folders','groups','stages','items','rows','largest'):
        if k in r and (not isinstance(r[k],list) or any(not isinstance(x,dict) for x in r[k])):return False
    for group in r.get('groups',[]):
        if not isinstance(group.get('paths'),list) or any(not isinstance(p,str) for p in group['paths']):return False
    return True

class Toolbox:
    def __init__(self,app,directory):
        self.app=app;self.directory=Path(directory)/'tools';self.directory.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.cancel=threading.Event();self.selections={};self.previews={};self.power=PowerLease();self.reports=[];self.process=None
        self.backend=app.backend
        if os.name=='nt' and not app.demo:
            from .windows import Windows
            self.backend=Windows();self.backend.directory=Path(directory)
        self.state={'running':False,'kind':None,'stage':'','error':None,'result':None,'reports':[],'selection':None};self.journal=self.directory/'rename.json'
        for p in sorted(self.directory.glob('result-*.json'),reverse=True)[:50]:
            if len(self.reports)>=8:break
            try:
                if p.stat().st_size<512000:
                    r=json.loads(p.read_text(encoding='utf-8'))
                    if valid_report(r):
                        if not isinstance(r.get('id'),str) or not re.fullmatch(r'result-[0-9]{1,25}',r['id']):r['id']=p.stem
                        self.reports.append(r)
            except (ValueError,OSError,TypeError,RecursionError,UnicodeError):pass
        self.state['reports']=self.reports;self.publish()
    def publish(self):
        with self.lock:value=copy.deepcopy({**self.state,'reports':[{k:r.get(k) for k in ('id','kind','title','time','demo')} for r in self.reports]})
        value['power']=self.power.state()
        with self.app.lock:self.app.data['toolbox']=value;self.app.data_revision+=1
    def open_report(self,ident):
        with self.lock:
            if self.state['running']:raise ValueError('Дождитесь завершения инструмента')
            r=next((r for r in self.reports if r.get('id')==ident),None)
            if not r:raise ValueError('Результат больше не хранится')
            self.state['result']=copy.deepcopy(r)
        self.publish();return {'ok':True}
    def stage(self,text):
        check(self.cancel)
        with self.lock:self.state['stage']=str(text)[:200]
        self.publish()
    def select(self,path,kind):
        from .storage import linked
        p=Path(path)
        if linked(p) or kind=='folder' and not p.is_dir() or kind=='file' and not p.is_file():raise ValueError('Выберите обычный файл или папку')
        p=p.resolve();s=p.stat();token=secrets.token_urlsafe(24);r={'token':token,'path':str(p),'kind':kind,'expires':time.monotonic()+1800,'identity':[s.st_dev,s.st_ino]}
        with self.lock:self.selections={token:r};self.state['selection']={'token':token,'name':p.name or str(p),'kind':kind,'path':str(p)}
        self.publish();return self.state['selection']
    def target(self,body,kind,live=True):
        from .storage import linked
        with self.lock:r=copy.deepcopy(self.selections.get(body.get('selection'))) if isinstance(body.get('selection'),str) else None
        if not r or r['kind']!=kind or time.monotonic()>r['expires']:raise ValueError('Сначала выберите '+('папку' if kind=='folder' else 'файл'))
        if self.app.demo or not live:return Path(r['path'])
        p=Path(r['path']);s=p.stat()
        if linked(p) or [s.st_dev,s.st_ino]!=r['identity'] or p.resolve()!=p:raise ValueError('Выбранный объект изменился. Выберите снова.')
        return p
    def unfinished_rename(self):
        for p in (self.directory/'rename-recovery.json',self.directory/'rename-return.json',self.journal):
            if not p.is_file():continue
            if p.stat().st_size>512000:raise ValueError('Журнал переименования требует ручной проверки; новый журнал не перезаписывается')
            try:r=json.loads(p.read_text(encoding='utf-8'))
            except (ValueError,OSError):raise ValueError('Не удалось прочитать прошлое переименование; новый журнал не перезаписывается') from None
            if r.get('state') in ('prepared','error'):return p
        return None
    def prepare(self,body):
        from .files import rename_preview
        if body.get('kind')!='rename':raise ValueError('Неизвестное изменение файлов')
        if not self.app.demo and self.unfinished_rename():raise ValueError('Сначала восстановите имена после незавершённого переименования')
        root=Path(body['_target']) if '_target' in body else self.target(body,'folder');find=body.get('find');replace=body.get('replace','');job=({'root':'Демонстрация','rows':[{'before':'Фото 1.jpg','after':'Кадр 1.jpg'},{'before':'Фото 2.jpg','after':'Кадр 2.jpg'}]} if self.app.demo else rename_preview(root,find,replace));token=secrets.token_urlsafe(24)
        with self.lock:self.previews={token:{'job':job,'expires':time.monotonic()+90}}
        return {'token':token,'count':len(job['rows']),'rows':[{'before':r['before'],'after':r['after']} for r in job['rows']]}
    def start(self,kind,body):
        if not isinstance(kind,str) or kind not in KINDS:raise ValueError('Неизвестный инструмент')
        body=copy.deepcopy(body)
        if kind in ('hash','file_locks'):body['_target']=str(self.target(body,'file',live=False))
        if kind in ('disk_map','duplicates','offline_cache','rename_preview'):body['_target']=str(self.target(body,'folder',live=False))
        if kind in ('network_chain','latency'):body['host']=host_value(body.get('host','www.microsoft.com'))
        if kind=='offline_cache':
            from .catalog import APPS
            apps=body.get('apps')
            if body.get('confirmed') is not True:raise ValueError('Подтвердите загрузку установщиков')
            if not isinstance(apps,list) or not 1<=len(apps)<=len(APPS) or any(not isinstance(a,str) or a not in APPS for a in apps) or len(set(apps))!=len(apps):raise ValueError('Отметьте программы в каталоге')
        if kind=='rename':
            if body.get('confirmed') is not True:raise ValueError('Подтвердите переименование')
            with self.lock:p=self.previews.pop(body.get('token'),None) if isinstance(body.get('token'),str) else None
            if not p or time.monotonic()>p['expires']:raise ValueError('Предпросмотр устарел')
            body['_job']=p['job']
        if kind in ('rename_undo','rename_recover') and body.get('confirmed') is not True:raise ValueError('Подтвердите возврат имён')
        if kind=='hash' and body.get('expected') and not re.fullmatch('[A-Fa-f0-9]{64}',body['expected']):raise ValueError('SHA-256 должен содержать 64 шестнадцатеричных символа')
        with self.lock:
            if self.state['running']:raise ValueError('Инструмент уже работает')
            self.cancel.clear();self.state.update(running=True,kind=kind,stage='Подготовка',error=None,details=None)
        self.publish();threading.Thread(target=self._run,args=(kind,body),daemon=True).start()
    def stop(self):
        with self.lock:
            if self.state['running'] and self.state['kind'] in ('rename','rename_undo','rename_recover'):return False
            self.cancel.set();p=self.process
        if p and p.poll() is None:
            try:p.kill()
            except OSError:pass
        if self.backend is not self.app.backend:self.backend.stop_processes()
        return True
    def close(self):self.stop();self.power.close()
    def run_owned(self,args,timeout=20):
        p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000 if os.name=='nt' else 0)
        with self.lock:self.process=p
        end=time.monotonic()+timeout
        try:
            while True:
                check(self.cancel)
                try:out,err=p.communicate(timeout=.2);break
                except subprocess.TimeoutExpired:
                    if time.monotonic()>end:raise TimeoutError('Модуль превысил время ожидания')
            if p.returncode or len(out)>2*1024**2:raise ValueError('Модуль не вернул корректный результат')
            return json.loads(out.decode('utf-8-sig'))
        finally:
            if p.poll() is None:p.kill()
            p.communicate(timeout=3)
            with self.lock:self.process=None
    def file_job(self,kind,body):
        import queue
        spec=self.directory/('job-'+secrets.token_hex(12)+'.json');atomic_json(spec,{'kind':kind,'target':body['_target'],'expected':body.get('expected',''),'find':body.get('find'),'replace':body.get('replace',''),'identity':self.selections.get(body.get('selection'),{}).get('identity')})
        python=Path(sys.executable).with_name('python.exe');process=None;worker=None;messages=queue.Queue(maxsize=64)
        try:
            from .worker_process import worker_command
            process=subprocess.Popen(worker_command('file_worker',spec),stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
            with self.lock:self.process=process
            def pump():
                try:
                    while True:
                        line=process.stdout.readline(2*1024**2)
                        if not line:break
                        if len(line)>=2*1024**2:continue
                        try:r=json.loads(line)
                        except (ValueError,UnicodeError):continue
                        if r.get('phase')=='progress':
                            try:messages.put_nowait(r)
                            except queue.Full:pass
                        else:
                            while not self.cancel.is_set():
                                try:messages.put(r,timeout=.2);break
                                except queue.Full:continue
                finally:
                    try:messages.put(None,timeout=.3)
                    except queue.Full:pass
            worker=threading.Thread(target=pump,daemon=True);worker.start();end=time.monotonic()+240;result=None
            while process.poll() is None or worker.is_alive() or not messages.empty():
                check(self.cancel)
                if time.monotonic()>end:raise TimeoutError('Проверка файлов превысила ограничение времени')
                try:r=messages.get(timeout=.2)
                except queue.Empty:continue
                if r is None:continue
                if r.get('phase')=='progress':self.stage(r.get('message','Проверяем файлы'))
                elif r.get('phase')=='error':raise ValueError(r.get('message','Ошибка чтения файлов'))
                elif r.get('phase')=='result':result=r.get('result')
            if process.returncode or not isinstance(result,dict):raise ValueError('Модуль не вернул полный результат')
            return result
        finally:
            if process:
                if process.poll() is None:process.kill()
                process.communicate(timeout=3)
            if worker:worker.join(timeout=2)
            spec.unlink(missing_ok=True)
            with self.lock:self.process=None
    def _run(self,kind,body):
        self.backend.progress=self.stage;self.backend.cancel_event=self.cancel
        try:
            check(self.cancel)
            fn=lambda:self.demo(kind,body) if self.app.demo else self.execute(kind,body)
            titles={'rename':'Переименование файлов','rename_undo':'Возврат имён файлов','rename_recover':'Восстановление прерванного переименования','offline_cache':'Подготовка установщиков'}
            result=self.app.engine.external(titles[kind],fn) if kind in titles else fn()
            check(self.cancel);result.update(id='result-'+str(time.time_ns()),kind=kind,time=time.time(),demo=self.app.demo);result.setdefault('title','Результат инструмента')
            raw=json.dumps(result,ensure_ascii=False)
            if len(raw.encode())>512000:raise ValueError('Результат слишком большой')
            if kind not in ('pick_file','pick_folder','rename_preview'):
                atomic_json(self.directory/(result['id']+'.json'),result)
                with self.lock:self.reports=[result,*self.reports][:8];self.state['reports']=self.reports
                keep=sorted(self.directory.glob('result-*.json'),reverse=True)[8:]
                for p in keep:p.unlink(missing_ok=True)
            with self.lock:self.state.update(result=result,error=None)
        except Stopped:
            with self.lock:self.state.update(error='Проверка остановлена. Неполный результат не сохранён.',result=None)
        except Exception as e:
            with self.lock:self.state.update(error=str(e)[:500] if isinstance(e,(ValueError,OSError,TimeoutError)) else 'Не удалось завершить инструмент. Повторите проверку.',details=str(e)[:4000],result=None)
        finally:
            self.backend.progress=lambda text:None;self.backend.cancel_event=None
            with self.lock:self.state.update(running=False,stage='')
            self.publish()
    def execute(self,kind,body):
        from . import files,system_probes as ps
        b=self.backend
        if kind in ('pick_folder','pick_file'):
            requested='folder' if kind=='pick_folder' else 'file';r=b.psjson(PICKER_PS,{'kind':requested},timeout=180)
            return {'title':'Выбор '+('папки' if requested=='folder' else 'файла'),'selection':self.select(r['path'],requested)} if r and r.get('path') else {'title':'Выбор отменён'}
        if kind=='rename_preview':
            if self.unfinished_rename():raise ValueError('Сначала восстановите незавершённое переименование')
            if os.name=='nt':job=self.file_job(kind,body)
            else:
                self.target(body,'folder');job=files.rename_preview(body['_target'],body.get('find'),body.get('replace',''))
            token=secrets.token_urlsafe(24)
            with self.lock:self.previews={token:{'job':job,'expires':time.monotonic()+90}}
            return {'title':'Предпросмотр переименования','token':token,'count':len(job['rows']),'rows':[{'before':r['before'],'after':r['after']} for r in job['rows']]}
        if os.name=='nt' and kind in ('disk_map','duplicates','hash'):return self.file_job(kind,body)
        if kind in ('disk_map','duplicates','offline_cache'):self.target(body,'folder')
        if kind in ('hash','file_locks'):self.target(body,'file')
        if kind=='disk_map':return files.analyze(body['_target'],self.cancel,self.stage)
        if kind=='duplicates':return files.duplicates(body['_target'],self.cancel,self.stage)
        if kind=='hash':
            sha=files.hash_file(body['_target'],self.cancel,self.stage);expected=body.get('expected','').casefold()
            return {'title':'SHA-256 выбранного файла','sha256':sha,'name':Path(body['_target']).name,'matches':sha==expected if expected else None,'note':'Совпадение с указанным эталоном проверяет содержимое; само по себе не доказывает безопасность программы.'}
        if kind=='file_locks':
            from .file_locks import owners
            return {'title':'Кто использует файл','items':owners(body['_target']),'note':'Показаны доступные Restart Manager приложения. Дескрипторы и процессы не закрывались. Пустой список не гарантирует отсутствие блокировки.'}
        if kind=='rename':
            if self.unfinished_rename():raise ValueError('Сначала восстановите имена после незавершённого переименования')
            return files.rename_apply(body['_job'],self.journal)
        if kind=='rename_recover':
            from .files import recovery_plan
            journal=self.unfinished_rename()
            if not journal:raise ValueError('Незавершённых переименований нет')
            job=recovery_plan(journal);saved=json.loads(journal.read_text(encoding='utf-8'));result=files.rename_apply(job,self.directory/'rename-recovery.json') if job['rows'] else {'count':0}
            saved['state']='recovered';atomic_json(journal,saved);return {**result,'title':'Исходные имена восстановлены','note':'Возвращены только проверенные исходные файлы. Посторонние файлы не перезаписывались.'}
        if kind=='rename_undo':
            if not self.journal.is_file() or self.journal.stat().st_size>512000:raise ValueError('Нет сохранённого переименования')
            saved=json.loads(self.journal.read_text(encoding='utf-8'))
            if saved.get('state')!='confirmed' or not isinstance(saved.get('rows'),list) or len(saved['rows'])>500:raise ValueError('Возврат недоступен')
            job={'root':saved['root'],'rows':[{'before':r['after'],'after':r['before'],'identity':r['identity']} for r in saved['rows']]}
            result=files.rename_apply(job,self.directory/'rename-return.json');saved['state']='returned';atomic_json(self.journal,saved);result.update(title='Прежние имена возвращены',can_undo=False);return result
        scripts={'processes':ps.PROCESSES_PS,'connections':ps.CONNECTIONS_PS,'battery':ps.BATTERY_PS,'security':ps.SECURITY_PS,'peripherals':ps.PERIPHERALS_PS,'printers':ps.PRINTERS_PS,'startup_extra':ps.STARTUP_EXTRA_PS,'crashes':ps.CRASHES_PS}
        if kind in scripts:return {'title':{'processes':'Процессы и нагрузка','connections':'Соединения и владельцы','battery':'Батарея ноутбука','security':'Состояние Microsoft Defender','peripherals':'Подключённые устройства','printers':'Принтеры и очереди','startup_extra':'Задачи и службы автозапуска','crashes':'Сбои и изменения за 14 дней'}[kind],'data':b.psjson(scripts[kind],timeout=35),'note':{'processes':'Снимок общесистемных счётчиков. I/O включает доступный ввод/вывод, не только физический диск.','connections':'Это перечень соединений, не скорость трафика процессов. UDP не предоставляет удалённую сторону в этой таблице.','startup_extra':'Службы показаны для просмотра. Не отключайте неизвестные системные компоненты.','battery':'Ёмкости и циклы доступны не на всех батареях. Предел зарядки зависит от производителя.','security':'Состояние штатной защиты, не заключение об отсутствии вредоносного ПО.'}.get(kind,'Неподдерживаемые показатели остаются недоступными.')}
        if kind=='latency':
            from .network_tools import latency
            raw=b.psjson(ps.LATENCY_PS,{'host':body['host']},timeout=20);return {'title':'Ответы узла '+body['host'],'host':body['host'],'data':latency(raw)}
        if kind=='wifi':
            from .wifi import current
            return {'title':'Текущее Wi-Fi соединение','items':current(),'note':'Согласованные скорости соединения отличаются от скорости интернета. Данные зависят от разрешений Windows.'}
        if kind=='network_chain':
            host=body['host'];data=b.psjson(ps.NETWORK_PS,{'host':host},timeout=20);stages=[];addresses=data.get('addresses',[]);stages.append({'name':'IP-адрес' if data.get('ip_literal') else 'DNS','milliseconds':data.get('dns_ms'),'status':'passed' if addresses else 'unavailable','detail':', '.join(addresses) if addresses else data.get('dns_error') or 'Адрес не получен'})
            from .network_tools import connect
            stages+=connect(host,addresses,self.cancel,self.stage)
            return {'title':'Соединение с '+host,'host':host,'stages':stages,'adapters':data.get('adapters',[]),'note':'Проверяется этот узел и порт 443; результат не описывает все сайты. Время TCP/TLS не является ICMP ping или скоростью канала.'}
        if kind=='drive_health':
            data=rows(b.psjson(ps.DISKS_PS,timeout=20));items=[];python=Path(sys.executable).with_name('python.exe')
            for row in data:
                check(self.cancel);self.stage('Проверяем накопитель: '+str(row.get('name',''))[:100])
                if str(row.get('bus','')).casefold()=='nvme':
                    try:
                        from .worker_process import worker_command
                        row['nvme']=self.run_owned(worker_command('drive_health',row['number']),timeout=12)
                    except (OSError,ValueError,TimeoutError):row['nvme']={'available':False,'reason':'Контроллер не предоставил NVMe SMART'}
                items.append(row)
            return {'title':'Накопители и доступный NVMe SMART','items':items,'note':'Читаются сведения Windows и NVMe SMART. USB/RAID и SATA могут не предоставлять эти данные; отсутствие SMART не означает исправность. Percentage Used — расход ресурса производителя, не универсальная оценка здоровья.'}
        if kind=='offline_cache':
            from .offline import download
            return download(b,body['_target'],body['apps'],self.cancel,self.stage)
        if kind=='prepare_transfer':
            from .transfer import snapshot
            from .software import summary
            programs,notes=self.app.software.read()
            result=snapshot(self.app.info,[summary(r) for r in programs],self.app.care.backups());result['notes']=notes;return result
        raise ValueError('Инструмент недоступен')
    def demo(self,kind,body):
        self.stage('Демонстрационный пример');self.cancel.wait(.2);check(self.cancel)
        if kind in ('pick_folder','pick_file'):
            token=secrets.token_urlsafe(24);requested='folder' if kind=='pick_folder' else 'file';self.selections={token:{'token':token,'kind':requested,'path':'Демонстрация','expires':time.monotonic()+1800,'identity':[0,0]}};self.state['selection']={'token':token,'name':'Папка · пример' if requested=='folder' else 'Файл · пример','kind':requested,'path':'Демонстрация'};return {'title':'Выбран демонстрационный объект'}
        if kind=='disk_map':return {'title':'Место в выбранной папке','files':1240,'bytes':24*1024**3,'folders':[{'name':'Игры','bytes':16*1024**3},{'name':'Видео','bytes':6*1024**3},{'name':'Документы','bytes':2*1024**3}],'largest':[{'path':'Видео/Пример.mp4','bytes':4*1024**3}],'limited':False,'skipped':2,'note':'Пример. Ваши папки не читались.'}
        if kind=='rename_preview':return {'title':'Предпросмотр · пример',**self.prepare({**body,'kind':'rename'})}
        if kind=='hash':return {'title':'SHA-256 · пример','sha256':'a'*64,'matches':body.get('expected')=='a'*64 if body.get('expected') else None}
        if kind=='duplicates':return {'title':'Совпадающие файлы · пример','groups':[{'sha256':'b'*64,'bytes_each':1024**2,'paths':['Папка/Копия.jpg','Другая/Копия.jpg'],'copies':2}],'note':'Файлы не удалялись.'}
        if kind=='file_locks':return {'title':'Кто использует файл · пример','items':[{'pid':4242,'name':'Приложение · пример'}]}
        if kind in ('rename','rename_undo','rename_recover'):return {'title':'Демонстрация переименования','count':2,'can_undo':kind=='rename','note':'Файлы не изменялись.'}
        if kind=='network_chain':return {'title':'Соединение · пример','stages':[{'name':x,'status':'passed','milliseconds':12} for x in ('DNS','TCP · 443','TLS')],'host':body['host'],'note':'Это демонстрация.'}
        if kind=='wifi':return {'title':'Wi-Fi · пример','items':[{'name':'Адаптер Wi-Fi','connected':True,'available':True,'ssid':'Домашняя сеть · пример','quality':82,'rx_link_mbps':866,'tx_link_mbps':866}]}
        if kind=='processes':return {'title':'Процессы · пример','data':[{'id':4242,'name':'Игра · пример','cpu_percent':18,'private_mb':2400,'io_read_bps':128000}]}
        if kind=='connections':return {'title':'Соединения · пример','data':{'tcp':[{'process':'Браузер · пример','pid':4243,'remote':'203.0.113.1','remote_port':443,'state':'Established'}],'udp':[]}}
        if kind=='drive_health':return {'title':'Накопители · пример','items':[{'number':0,'name':'NVMe SSD · пример','bus':'NVMe','health':'Healthy','nvme':{'available':True,'temperature_c':42,'percentage_used':3,'media_errors':'0'}}]}
        if kind=='startup_extra':return {'title':'Задачи и службы · пример','data':{'tasks':[{'name':'Updater · пример','enabled':True,'source':'Планировщик'}],'services':[{'name':'Служба · пример','state':'Running','readonly':True}]}}
        if kind=='offline_cache':return {'title':'Установщики · пример','path':'Демонстрация','items':[{'name':a} for a in body['apps']],'note':'Загрузки и установки не выполнялись.'}
        if kind=='prepare_transfer':
            from .transfer import snapshot
            from .software import summary
            programs,_=self.app.software.read();r=snapshot(self.app.info,[summary(p) for p in programs],['Drivers-Demo']);r['note']='Демонстрационный набор. Настройки этого ПК не читались.';return r
        if kind=='latency':
            from .network_tools import latency
            return {'title':'ICMP · пример','data':latency({'samples':[{'ok':True,'milliseconds':v,'status':'Success'} for v in [14,15,14,16,15,14,15,14]]})}
        if kind=='crashes':return {'title':'Сбои · пример','data':{'events':[{'id':41,'source':'Kernel-Power','kind':'restart','time':'2026-10-19T10:00:00Z','message':'Пример: Windows обнаружила некорректное завершение. Причина не установлена.'}],'dumps':[],'notes':[]},'note':'Демонстрация. Журнал этого ПК не читался.'}
        return {'title':{'battery':'Батарея · пример','security':'Защита · пример','peripherals':'Устройства · пример','printers':'Принтеры · пример'}[kind],'data':{'note':'Демонстрационные данные; оборудование не проверялось.'}}
