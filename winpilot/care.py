"""Bounded diagnostic jobs, evidence-based findings and confirmed repairs."""
import copy
import json
import math
import re
import secrets
import threading
import time
from pathlib import Path
from .workspace import atomic_json

KINDS={'game','memory','audio','network','system','speed','benchmark','observe','integrity','repair_system','driver_backup','driver_restore','voice'}

def finding(code,title,detail,level='info',action=None,target=None):
    return {'id':code+(':'+str(target) if target is not None else ''),'title':title,'detail':detail,'level':level,'action':action,'target':target}

def audio_findings(raw):
    result=[];rows=raw.get('endpoints',[])
    for flow,label in [(0,'выхода звука'),(1,'микрофона')]:
        devices=[r for r in rows if r.get('flow')==flow]
        if not devices:result.append(finding('missing_audio_'+str(flow),'Нет доступного '+label,'Windows не предоставила активное устройство. Проверьте подключение и драйвер; физическую причину по этому признаку определить нельзя.','warning'))
        for d in devices:
            if d.get('controllable') and (d.get('mute') or d.get('volume')==0):
                result.append(finding('muted','Звук выключен: '+d['name'],'Громкость — '+str(d.get('volume','?'))+'%; отключение звука — '+('да' if d.get('mute') else 'нет')+'.','problem','audio_level',d['id']))
    for s in raw.get('services',[]):
        if s.get('status')=='Stopped':result.append(finding('service','Остановлена служба '+s['name'],'Она нужна для работы звука. Предлагаем запустить и повторить проверку.','problem','audio_service',s['name']))
    if raw.get('microphone_access')=='Deny':result.append(finding('mic_access','Доступ к микрофону запрещён','Обнаружен запрет для текущего пользователя. Разрешение влияет на приложения; управление политиками организации не выполняется.','problem','mic_access' if raw.get('microphone_policy')!=2 else None))
    if raw.get('microphone_desktop_access')=='Deny':result.append(finding('desktop_mic','Запрещён микрофон для настольных приложений','Обнаружено отдельное ограничение для desktop-программ. Оно может действовать при общем разрешении микрофона.','problem'))
    if raw.get('microphone_policy')==2:result.append(finding('policy_mic','Микрофон запрещён политикой организации','Ограничение не меняется автоматически. Обратитесь к администратору этого компьютера.','problem'))
    if raw.get('probe_error') or raw.get('audio_error') or raw.get('sessions_unavailable'):result.append(finding('audio_partial','Часть проверок недоступна','Смотрите технические сведения. Вывод о состоянии непроверенных компонентов не делается.','warning'))
    for row in raw.get('sessions',[]):
        if row.get('mute') or row.get('volume')==0:result.append(finding('session','Отдельно заглушено приложение: '+row.get('name','Приложение'),'Системная громкость может быть нормальной. Включить звук только этой аудиосессии.','problem','session_unmute',row['id']))
    for d in raw.get('drivers',[]):
        if d.get('problem'):result.append(finding('audio_driver','Windows сообщает об ошибке устройства: '+d.get('name','Аудиоустройство'),'Код '+str(d['problem'])+'. Проверьте совместимые обновления в разделе драйверов.','problem'))
    if not result:result.append(finding('audio_ok','Явных программных причин не найдено','Проверьте сигнал динамиков и запись микрофона. Успешная отправка сигнала не доказывает, что динамики физически звучат.','ok'))
    return result

def network_findings(raw):
    result=[];adapters=raw.get('adapters',[]);active=[a for a in adapters if a.get('up')]
    if raw.get('adapters_unknown'):result.append(finding('adapters_unknown','Windows не предоставила сведения об адаптерах','Часть диагностики недоступна; отсутствие данных не означает отсутствие подключения.','warning'))
    if not active and not raw.get('adapters_unknown'):result.append(finding('no_link','Нет активного сетевого подключения','Проверьте кабель или подключение к Wi-Fi. Сброс настроек в этом состоянии не предлагается.','problem'))
    for a in active:
        if any(str(ip).startswith('169.254.') for ip in a.get('ipv4',[])) and a.get('dhcp'):
            result.append(finding('dhcp','Не получен адрес от роутера: '+a['name'],'Обнаружен автоматический адрес 169.254.x.x. Можно запросить адрес повторно у DHCP-сервера.','problem','dhcp_renew',a['guid']))
    if raw.get('dns') is False:
        result.append(finding('dns','Не удалось разрешить проверочное доменное имя','Это наблюдение, а не доказанная поломка DNS. Очистка локального DNS-кэша — первый ограниченный шаг; VPN и настройки адаптеров сохраняются.','warning','dns_flush'))
    if raw.get('https') is False:result.append(finding('external','Проверочный HTTPS-сервер недоступен','Причина может быть в маршруте, сервере, VPN, прокси или фильтрации. По одному узлу нельзя обвинить провайдера.','warning'))
    for ping in raw.get('pings',[]):
        if ping.get('sent',0) and ping.get('received',0)<ping['sent']:result.append(finding('ping_'+ping['label'],'Часть ICMP-запросов без ответа: '+ping['label'],f"Ответов {ping.get('received',0)} из {ping['sent']}. ICMP может фильтроваться; это не доказательство потерь игрового трафика.",'warning'))
    if type(raw.get('dns')) is not bool or type(raw.get('https')) is not bool:result.append(finding('network_partial','Часть проверок подключения недоступна','Не удалось получить результат проверки DNS или защищённого подключения. Повторите проверку; состояние непроверенных компонентов неизвестно.','warning'))
    if not result:result.append(finding('network_ok','Базовое подключение отвечает','Проверочные DNS и HTTPS доступны. Для оценки скорости и задержки под нагрузкой запустите отдельный тест.','ok'))
    return result

def performance_findings(samples):
    result=[]
    if len(samples)<3:return [finding('few_samples','Недостаточно измерений','Нужно не менее трёх корректных отсчётов. Запустите наблюдение снова.','warning')]
    def sustained(key,threshold):
        values=[r[key] for r in samples if isinstance(r.get(key),(int,float))]
        return len(values)>=3 and sum(v>=threshold for v in values)/len(values)>=.6
    if sustained('ram_percent',90):result.append(finding('ram_pressure','Во время наблюдения была почти заполнена память','Занято ≥90% памяти в большинстве отсчётов. Это может вызывать задержки; посмотрите процессы с большим потреблением.','warning'))
    if sustained('gpu',95):result.append(finding('gpu_busy','Графический движок долго работал почти на пределе','Вероятно ограничение производительностью GPU в наблюдавшейся нагрузке. Снижение разрешения или качества — проверяемый следующий шаг. Счётчики относятся ко всей системе.','warning'))
    if sustained('cpu_core',95):result.append(finding('cpu_core_busy','Одно или несколько ядер долго были почти полностью заняты','Возможен упор в процессор или фоновую задачу. Это не доказывает ограничение конкретной игры.','warning'))
    if sustained('disk_ms',50):result.append(finding('disk_latency','Наблюдались длительные обращения к диску','Среднее время операций ≥50 мс в большинстве отсчётов. Возможны фоновые операции или ограничение накопителя; это не диагноз неисправности.','warning'))
    if not result:result.append(finding('no_pressure','Устойчивой перегрузки по доступным счётчикам не видно','Это не исключает короткие просадки, перегрев или ограничения игры. FPS, frametime и температуры этим тестом не измеряются.','info'))
    missing=[name for key,name in [('gpu','GPU'),('cpu_core','ядра CPU'),('disk_ms','задержки диска')] if not any(isinstance(r.get(key),(int,float)) for r in samples)]
    if missing:result.append(finding('missing_counters','Часть счётчиков недоступна',', '.join(missing)+'. Отсутствующие данные не заменяются нулями.','info'))
    return result

def valid_report(r):
    """Reject corrupt persisted data before it reaches the renderer or repair preview."""
    if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',r['id']):return False
    if not isinstance(r.get('kind'),str) or r['kind'] not in KINDS|{'fix'}:return False
    if not isinstance(r.get('title'),str) or not 1<=len(r['title'])<=500:return False
    stamp=r.get('time')
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=stamp<=253402300799:return False
    rows=r.get('findings')
    if not isinstance(rows,list) or len(rows)>256:return False
    for row in rows:
        if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or len(row[k])>limit for k,limit in [('id',1200),('title',1000),('detail',16000)]):return False
        if row.get('level') not in ('ok','info','warning','problem'):return False
        if row.get('action') not in (None,'audio_level','audio_service','mic_access','session_unmute','dns_flush','dhcp_renew'):return False
    if not isinstance(r.get('metrics',{}),dict):return False
    for value in r.get('metrics',{}).values():
        if value is not None and (type(value) not in (int,float,str) or isinstance(value,str) and len(value)>4000):return False
    if not isinstance(r.get('samples',[]),list) or len(r.get('samples',[]))>500 or any(not isinstance(v,dict) for v in r.get('samples',[])):return False
    if not isinstance(r.get('frames',[]),list) or len(r.get('frames',[]))>300 or any(not isinstance(v,dict) for v in r.get('frames',[])):return False
    if 'source_kind' in r and r['source_kind'] not in ('audio','network'):return False
    try:json.dumps(r,allow_nan=False)
    except (ValueError,TypeError):return False
    return True

def reject_constant(value):raise ValueError('Некорректное число в сохранённом результате')

class Cancelled(Exception):pass

class CareCenter:
    def __init__(self,app):
        self.app=app;self.lock=threading.RLock();self.cancel=threading.Event();self.process=None;self.pending={};self.undo={};self.voice=None
        self.directory=Path(app.engine.directory)/'care';self.directory.mkdir(exist_ok=True)
        self.state={'running':False,'stage':'','reports':[],'voice_report':None}
        self.report_paths={}
        for p in sorted(self.directory.glob('report-*.json'),reverse=True)[:100]:
            try:
                if p.stat().st_size>=1024*1024:raise ValueError('Результат слишком большой')
                r=json.loads(p.read_text(encoding='utf-8'),parse_constant=reject_constant)
                if not valid_report(r):raise ValueError('Повреждён результат')
                if r['id'] in self.report_paths:continue
                self.state['reports'].append(r);self.report_paths[r['id']]=p
                if len(self.state['reports'])==8:break
            except (ValueError,OSError,TypeError):self.state['history_warning']='Некоторые сохранённые результаты не удалось прочитать. Повторите нужную проверку.'
    def publish(self):
        try:
            row=json.loads((self.directory/'last-repair-undo.json').read_text(encoding='utf-8'))
            undo_report=row.get('report') if isinstance(row,dict) else None
        except (ValueError,OSError):undo_report=None
        self.state['undo_report']=undo_report if isinstance(undo_report,str) else None
        with self.app.lock:self.app.data['care']=copy.deepcopy(self.state);self.app.data_revision+=1
    def store_report(self,report):
        if not valid_report(report):raise ValueError('Некорректный результат проверки')
        path=self.directory/('report-'+str(time.time_ns())+'.json');atomic_json(path,report)
        with self.lock:
            self.report_paths[report['id']]=path;self.state['reports']=[report,*self.state['reports']][:8]
        keep={r['id'] for r in self.state['reports']}
        for ident,old in list(self.report_paths.items()):
            if ident not in keep:
                try:old.unlink(missing_ok=True);self.report_paths.pop(ident,None)
                except OSError:pass
    def finish_undo(self,report_id,path):
        warnings=[]
        try:path.unlink()
        except OSError as exc:warnings.append(str(exc))
        with self.lock:
            self.undo={}
            for r in self.state['reports']:
                if r['id']!=report_id:continue
                r.pop('undo',None);r['undo_applied']=True
                target=self.report_paths.get(report_id)
                if target is None:
                    for candidate in self.directory.glob('report-*.json'):
                        try:
                            if json.loads(candidate.read_text(encoding='utf-8')).get('id')==report_id:target=candidate;break
                        except (ValueError,OSError,AttributeError):continue
                if target:
                    try:atomic_json(target,r)
                    except OSError as exc:warnings.append(str(exc))
            if warnings:self.state.update(error='Прежнее значение возвращено, но результат не удалось сохранить.',details='; '.join(warnings)[:6000])
        self.publish();return {'ok':True}

    def stage(self,text):
        if self.cancel.is_set():raise Cancelled('Проверка остановлена')
        with self.lock:self.state['stage']=text
        self.publish()
    def stop(self):
        if self.state.get('running') and self.state.get('kind') in {'repair_system','integrity','driver_backup','driver_restore','fix'}:return False
        self.cancel.set()
        with self.lock:
            p=self.process
            if p is not None and p.poll() is None:p.kill()
        return True
    def backups(self):
        if self.app.demo:return ['Drivers-Demo']
        from .care_windows import driver_root
        root=driver_root()
        if not root.exists():return []
        return [p.name for p in sorted(root.iterdir(),reverse=True) if p.is_dir() and not p.is_symlink() and p.name.startswith('Drivers-') and (p/'KrolikControl-backup.json').is_file()][:30]
    def undo_last(self,report_id):
        if self.state['running']:raise ValueError('Операция уже идёт')
        path=self.directory/'last-repair-undo.json'
        if not path.is_file():raise ValueError('Нет сохранённого исправления')
        row=json.loads(path.read_text(encoding='utf-8'))
        if row.pop('report',None)!=report_id:raise ValueError('Это исправление уже заменено более новым')
        if row.get('kind')=='session':
            from .audio import audio_sessions,set_session
            current=next((r for r in audio_sessions() if r['id']==row.get('target')),None)
            if not current or current['mute'] or current['volume']!=row.get('applied'):raise ValueError('Сессия закрылась или значение изменилось; возврат не выполнен')
            set_session(row['target'],row['mute'],row['volume']);return self.finish_undo(report_id,path)
        if row!={'kind':'mic_access','previous':'Deny'}:raise ValueError('Недоступный возврат')
        if not self.app.demo:
            from .care_windows import psjson
            result=psjson(self,r"$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone';if((Get-ItemProperty $key).Value -ne 'Allow'){throw 'Разрешение изменилось'};Set-ItemProperty -LiteralPath $key -Name Value -Value 'Deny';@{value=(Get-ItemProperty $key).Value}|ConvertTo-Json",timeout=10)
            if result.get('value')!='Deny':raise ValueError('Возврат не подтверждён')
        return self.finish_undo(report_id,path)
    def start(self,kind,body=None):
        body=body or {}
        if not isinstance(kind,str) or kind not in KINDS:raise ValueError('Неизвестная проверка')
        with self.lock:
            if self.state['running']:raise ValueError('Дождитесь завершения проверки или остановите её')
            if kind in {'repair_system','driver_restore'} and body.get('confirmed') is not True:raise ValueError('Нужно подтверждение действия')
            if kind in {'speed','benchmark','memory','game','voice','driver_backup'} and body.get('confirmed') is not True:raise ValueError('Нужно подтверждение теста')
            if kind=='game':
                from .game_capture import options
                options(self,body)
                if not self.app.demo and not (self.app.info or {}).get('admin'):raise ValueError('Для записи кадров нужны права администратора')
            if kind=='memory':
                from .memory_test import options
                options(body)
            if kind=='observe' and (type(body.get('seconds',30))!=int or body.get('seconds',30) not in (30,60)):raise ValueError('Выберите 30 или 60 секунд')
            if kind=='voice':
                row=next((r for r in (self.app.info or {}).get('endpoints',[]) if r['id']==body.get('id') and r['flow']==1),None)
                if not row:raise ValueError('Выберите подключённый микрофон')
            if kind in {'integrity','repair_system','driver_backup','driver_restore'} and not self.app.demo and not (self.app.info or {}).get('admin'):raise ValueError('Для этой операции нужны права администратора')
            self.cancel.clear();self.state.update(running=True,kind=kind,stage='Подготовка',error='',details='');self.voice=None if kind=='voice' else self.voice
            if kind=='voice':self.state['voice_report']=None
        self.publish();threading.Thread(target=self._run,args=(kind,body),daemon=True).start()
    def _run(self,kind,body):
        report=None
        try:
            if self.app.demo:
                from .care_windows import demo_run
                result=demo_run(self,kind,body)
            else:
                from .care_windows import run
                result=run(self,kind,body)
            if self.cancel.is_set():raise Cancelled('Проверка остановлена')
            report={'id':secrets.token_hex(12),'kind':kind,'time':time.time(),'demo':self.app.demo,**result}
            if kind=='voice':self.state['voice_report']=report['id'] if self.voice is not None else None
            self.store_report(report)
        except Cancelled:
            with self.lock:self.state['error']='Остановлено. Незавершённые измерения не считаются результатом.'
        except Exception as exc:
            with self.lock:
                self.state['error']=str(exc)[:1000] if kind in ('memory','game') and isinstance(exc,(ValueError,TimeoutError)) else 'Сервис замера скорости недоступен или не завершил тест. Проверьте подключение и повторите.' if kind=='speed' else 'Не удалось завершить операцию. Повторите или откройте сведения.'
                self.state['details']=str(exc)[:6000]
        finally:
            if kind=='voice' and (self.cancel.is_set() or self.state.get('error')):self.voice=None;self.state['voice_report']=None
            with self.lock:self.state.update(running=False,stage='');self.process=None
            self.publish()
    def preview(self,report_id,finding_id):
        with self.lock:
            if self.state['running']:raise ValueError('Сначала завершите проверку')
            report=next((r for r in self.state['reports'] if r['id']==report_id),None)
            row=next((f for f in (report or {}).get('findings',[]) if f['id']==finding_id),None)
            if not row or not row.get('action'):raise ValueError('Повторите диагностику')
            if time.time()-report['time']>900:raise ValueError('Результат устарел. Повторите диагностику')
            source=report.get('source_kind',report['kind'])
            if source not in ('audio','network'):source='network' if row['action'] in ('dns_flush','dhcp_renew') else 'audio'
            token=secrets.token_urlsafe(24);self.pending={token:{'row':copy.deepcopy(row),'source_kind':source,'expires':time.monotonic()+90}}
            return {'token':token,'title':row['title'],'detail':row['detail'],'action':row['action']}
    def fix(self,token):
        with self.lock:
            if self.state['running']:raise ValueError('Операция уже идёт')
            pending=self.pending.pop(token,None)
            if not pending or pending['expires']<time.monotonic():raise ValueError('Подтвердите исправление заново')
            row=pending['row']
            if row['action']=='audio_level':return {'plan':{'version':1,'audio':[{'id':row['target'],'mute':False,'volume':70}]}}
            if row['action'] in {'dns_flush','dhcp_renew','audio_service'} and not self.app.demo and not (self.app.info or {}).get('admin'):raise ValueError('Нужны права администратора')
            self.active_repair_source=pending['source_kind'];self.active_repair=secrets.token_hex(12);self.cancel.clear();self.state.update(running=True,kind='fix',stage='Исправление',error='',details='')
        self.publish();threading.Thread(target=self._fix,args=(row,),daemon=True).start();return {'started':True}
    def _fix(self,row):
        try:
            from .care_windows import repair
            result=repair(self,row) if not self.app.demo else {'title':'Демонстрационное исправление','findings':[finding('demo_fix','Демонстрация','Реальная система не менялась.','info')]}
            report={'id':self.active_repair,'kind':'fix','source_kind':self.active_repair_source,'time':time.time(),'demo':self.app.demo,**result}
            self.store_report(report)
        except Exception as exc:
            with self.lock:self.state['error']='Исправление не подтверждено. Повторите диагностику.';self.state['details']=str(exc)[:6000]
        finally:
            with self.lock:self.state.update(running=False,stage='')
            self.publish()
