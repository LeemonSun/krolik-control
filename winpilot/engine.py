"""Validation, operation planning, journaling and sequential execution."""
import copy
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from .catalog import BY_KEY, APPS
from .windows import REG


def now(): return dt.datetime.now().astimezone().isoformat(timespec='seconds')

def validate_plan(plan,info,updates,*,demo=False):
    if not isinstance(plan,dict): raise ValueError('Профиль должен быть JSON-объектом')
    if set(plan)-{'version','settings','displays','brightness','audio','audio_defaults','audio_routing_ack','apps','updates','adapter','restore_point','upgrades','startup','layout','languages','prepare_apps'}: raise ValueError('Неизвестные поля профиля')
    from .profile_audio import validate_defaults
    validate_defaults(plan,info,demo)
    if type(plan.get('version',1))!=int or plan.get('version',1)!=1: raise ValueError('Неподдерживаемая версия профиля')
    settings=plan.get('settings',{})
    if not isinstance(settings,dict): raise ValueError('Некорректные настройки')
    for key,value in settings.items():
        if key not in BY_KEY or not isinstance(value,str): raise ValueError(f'Неизвестная настройка: {key}')
        if BY_KEY[key].group in info.get('pending_groups',[]):raise ValueError('Параметры этого раздела ещё определяются')
        allowed={x['id']:x['name'] for x in info.get('time_zones',[])} if key=='time_zone' else BY_KEY[key].choices if key!='power_plan' else {x['id']:x['name'] for x in info.get('power_plans',[])}
        if value not in allowed: raise ValueError(f'Недоступное значение: {key}')
        if int(info.get('build','0'))<BY_KEY[key].min_build: raise ValueError('Настройка недоступна в этой сборке Windows')
        if key.endswith('_dc') and not info.get('battery'): raise ValueError('На ПК не обнаружена батарея')
        if key=='taskbar_align' and int(info.get('build','0'))<22000: raise ValueError('Выравнивание доступно в Windows 11')
    languages=plan.get('languages',[])
    if not isinstance(languages,list) or len(languages)>32 or any(not isinstance(t,str) or not __import__('re').fullmatch(r'[A-Za-z0-9-]{2,80}',t) for t in languages) or len(set(t.lower() for t in languages))!=len(languages):raise ValueError('Некорректный список языков')
    allowed_languages={r['id'] for r in info.get('language_options',[])}|set(info.get('languages',[]))
    if any(t not in allowed_languages for t in languages):raise ValueError('Язык не найден в этой Windows')
    if languages and 'layouts' in settings:raise ValueError('Выберите список языков или пресет RU/EN')
    adapter=plan.get('adapter')
    if 'dns' in settings:
        if type(adapter)!=int or adapter not in [n['id'] for n in info.get('network',[])]: raise ValueError('Выберите существующий сетевой адаптер')
    displays=plan.get('displays',[])
    if not isinstance(displays,list) or len(displays)>16: raise ValueError('Некорректный список экранов')
    known={d['id']:d for d in info.get('displays',[])}; seen=set()
    for d in displays:
        if not isinstance(d,dict) or set(d)!={'id','mode','orientation'}: raise ValueError('Некорректный режим экрана')
        if not isinstance(d['id'],str) or d['id'] not in known or d['id'] in seen: raise ValueError('Монитор недоступен или указан дважды')
        seen.add(d['id'])
        if type(d['orientation'])!=int or d['orientation'] not in range(4): raise ValueError('Недопустимая ориентация')
        if d['mode'] not in [m['id'] for m in known[d['id']]['modes']]: raise ValueError('Режим экрана не поддерживается')
    if plan.get('layout'):
        from .display_layout import validate_layout
        validate_layout(plan['layout'],info.get('displays',[]))
        if displays:raise ValueError('Примените режимы экрана и расположение отдельными шагами')
    elif 'layout' in plan and plan['layout']!=[]:raise ValueError('Некорректная схема экранов')
    brightness=plan.get('brightness',[])
    if not isinstance(brightness,list) or len(brightness)>16: raise ValueError('Некорректная яркость')
    seen=set()
    for b in brightness:
        if not isinstance(b,dict) or set(b)!={'id','value'} or type(b['value'])!=int or not 0<=b['value']<=100: raise ValueError('Яркость должна быть от 0 до 100')
        if b['id'] not in [x['id'] for x in info.get('brightness',[])] or b['id'] in seen: raise ValueError('Регулировка яркости недоступна')
        seen.add(b['id'])
    audio=plan.get('audio',[])
    if not isinstance(audio,list) or len(audio)>128: raise ValueError('Некорректный список аудиоустройств')
    seen=set(); audio_ids={a['id'] for a in info.get('endpoints',[]) if a.get('controllable')}
    for a in audio:
        if not isinstance(a,dict) or set(a)-{'id','volume','mute'} or not isinstance(a.get('id'),str) or len(a)==1: raise ValueError('Некорректная аудионастройка')
        if a['id'] not in audio_ids or a['id'] in seen: raise ValueError('Аудиоустройство недоступно')
        seen.add(a['id'])
        if 'volume' in a and (type(a['volume'])!=int or not 0<=a['volume']<=100): raise ValueError('Громкость должна быть от 0 до 100')
        if 'mute' in a and type(a['mute'])!=bool: raise ValueError('Некорректное отключение звука')
    upgrades=plan.get('upgrades',[]);startup=plan.get('startup',[])
    if not isinstance(upgrades,list) or len(upgrades)>len(APPS) or any(not isinstance(a,str) or a not in APPS for a in upgrades) or len(set(upgrades))!=len(upgrades):raise ValueError('Некорректные обновления программ')
    available={r['id'] for r in info.get('programs',[]) if r.get('installed') and r.get('update_available')}
    if any(a not in available for a in upgrades):raise ValueError('Повторите проверку версий программ')
    if upgrades and not info.get('winget'):raise ValueError('Сначала выполните проверку программ')
    if not isinstance(startup,list) or len(startup)>500:raise ValueError('Некорректная автозагрузка')
    known_startup={r['id'] for r in info.get('startup',[]) if r.get('controllable')};seen_startup=set()
    for row in startup:
        if not isinstance(row,dict) or set(row)!={'id','enabled'} or not isinstance(row['id'],str) or row['id'] not in known_startup or type(row['enabled'])!=bool or row['id'] in seen_startup:raise ValueError('Автозагрузка изменилась; обновите список')
        seen_startup.add(row['id'])
    apps=plan.get('apps',[]); chosen_updates=plan.get('updates',[])
    if not isinstance(apps,list) or len(apps)>len(APPS) or any(not isinstance(a,str) or a not in APPS for a in apps): raise ValueError('Неизвестная программа')
    if set(apps)&set(upgrades):raise ValueError('Нельзя одновременно установить и обновить одну программу')
    if len(set(apps))!=len(apps): raise ValueError('Повтор программы')
    if type(plan.get('prepare_apps',False))!=bool:raise ValueError('Некорректный параметр подготовки установки')
    if (apps or plan.get('prepare_apps')) and int(info.get('build','0'))<17763:raise ValueError('Для установки программ нужна Windows 10 1809 или новее')
    if not isinstance(chosen_updates,list) or len(chosen_updates)>500: raise ValueError('Некорректный список обновлений')
    ids={u['id'] for u in updates}
    if any(not isinstance(u,str) or u not in ids for u in chosen_updates) or len(set(chosen_updates))!=len(chosen_updates): raise ValueError('Повторите поиск обновлений: выбранные записи недоступны')
    if type(plan.get('restore_point',False))!=bool: raise ValueError('Некорректный параметр точки восстановления')
    admin=any(BY_KEY[k].admin for k in settings) or chosen_updates or plan.get('restore_point')
    if admin and not demo and not info.get('admin') and not info.get('privileged_helper'): raise ValueError('Для DNS, драйверов, обновлений и точки восстановления запустите Krolik Control с правами администратора')
    return copy.deepcopy(plan)


def operations(plan,info,updates):
    result=[]
    def add(kind,key,value,title,**extra): result.append(dict(kind=kind,key=key,value=value,title=title,**extra))
    if plan.get('restore_point'): add('restore_point','','','Создать точку восстановления')
    if plan.get('prepare_apps') or (plan.get('apps') and not info.get('winget')):add('package_manager','apps','', 'Подготовить установку программ')
    # Power scheme first: timeouts must target the selected scheme.
    for key in sorted(plan.get('settings',{}),key=lambda k:0 if k=='power_plan' else 1):
        value=plan['settings'][key]; s=BY_KEY[key]
        choices={x['id']:x['name'] for x in info.get('time_zones',[])} if key=='time_zone' else s.choices if key!='power_plan' else {x['id']:x['name'] for x in info['power_plans']}
        add('setting',key,value,f'{s.title}: {choices[value]}',adapter=plan.get('adapter'))
    if plan.get('languages'):add('languages','languages',plan['languages'],'Языки ввода: '+', '.join(plan['languages']))
    for a in plan.get('audio_defaults',[]):
        name=next(x['name'] for x in info['endpoints'] if x['id']==a['id'])
        add('audio_default',a['id'],a,('Выход звука: ' if a['flow']==0 else 'Микрофон: ')+name+' · '+{0:'система',1:'приложения',2:'связь'}[a['role']])
    for a in plan.get('audio',[]): add('audio',a['id'],a,'Звук: '+next(x['name'] for x in info['endpoints'] if x['id']==a['id']))
    for app in plan.get('apps',[]): add('app',app,'',f'Установить {APPS[app][0]}')
    for app in plan.get('upgrades',[]):
        previous=next((r for r in info.get('programs',[]) if r['id']==app),{})
        add('upgrade',app,'',f'Обновить {APPS[app][0]}',before_version=previous.get('version'),expected_version=previous.get('available_version'))
    for row in plan.get('startup',[]):add('startup',row['id'],row['enabled'],('Включить: ' if row['enabled'] else 'Отключить: ')+next(r['name'] for r in info['startup'] if r['id']==row['id']))
    lookup={u['id']:u for u in updates}
    if any(lookup[i].get('driver') for i in plan.get('updates',[])):add('driver_safety','drivers','', 'Сохранить текущие сторонние драйверы перед обновлением')
    for ident in plan.get('updates',[]): add('update',ident,lookup[ident]['revision'],lookup[ident]['name'])
    for b in plan.get('brightness',[]): add('brightness',b['id'],b['value'],f'Яркость: {b["value"]}%')
    for d in plan.get('displays',[]): add('display',d['id'],d['mode'],f'{next(x["name"] for x in info["displays"] if x["id"]==d["id"])}: {d["mode"]}',orientation=d['orientation'],original_orientation=next(x['orientation'] for x in info['displays'] if x['id']==d['id']))
    if plan.get('layout'):add('layout','desktop',plan['layout'],'Расположение и основной экран')
    return result

class Engine:
    def __init__(self,backend,directory,demo=False):
        self.backend=backend; self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True)
        self.demo=demo; self.lock=threading.RLock(); self.cancel=threading.Event(); self.undo=[];self.revision=0
        self.on_finish=None; self.recovery_warning=None;self.undo_groups=[];self.active_undo_id=None
        backup=self.directory/'last-settings-backup.json'
        if backup.exists():
            try:
                from .recovery import checked_undo
                if backup.stat().st_size>2097152:raise ValueError('Резервная копия слишком большая')
                raw=json.loads(backup.read_text(encoding='utf-8'))
                if isinstance(raw,list):self.undo_groups=[{'id':'legacy','time':now(),'entries':checked_undo(raw)}] if raw else []
                else:
                    if not isinstance(raw,dict) or raw.get('version')!=2 or not isinstance(raw.get('groups'),list) or len(raw['groups'])>50:raise ValueError('Повреждён список отката')
                    for g in raw['groups']:
                        if not isinstance(g,dict) or set(g)!={'id','time','entries'} or not isinstance(g['id'],str) or not __import__('re').fullmatch(r'[a-zA-Z0-9-]{1,100}',g['id']) or not isinstance(g['time'],str) or len(g['time'])>100:raise ValueError('Повреждена группа отката')
                        checked_undo(g['entries'])
                    if sum(len(g['entries']) for g in raw['groups'])>2000:raise ValueError('Слишком много записей отката')
                    self.undo_groups=raw['groups']
                self.undo=[v for g in self.undo_groups for v in g['entries']]
            except Exception:
                self.recovery_warning='Сохранённая резервная копия не прошла проверку; автоматический откат отключён.'
        self.state={'running':False,'items':[],'finished':False,'reboot':False,'log':None,'can_undo':bool(self.undo)}
        from .pending import PendingChecks
        self.pending=PendingChecks(self.directory)
        self.history=self._history()
    def _history(self):
        result=[]
        for path in sorted(self.directory.glob('*-*.jsonl'),key=lambda p:p.name.split('-',1)[-1],reverse=True)[:50]:
            try:
                if path.stat().st_size>2097152:continue
                rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
                latest={str(r.get('index',r['title'])):r for r in rows}
                if not latest:continue
                values=list(latest.values());interrupted=any(v['status'] in ('running','queued') for v in values)
                result.append({'id':path.name,'time':values[-1]['time'],'kind':'undo' if path.name.startswith('undo-') else 'action' if path.name.startswith('action-') else 'apply','title':values[-1]['title'],
                    'success':sum(v['status']=='success' for v in values),'errors':sum(v['status']=='error' for v in values),'closed':sum(v['status'] in ('closed','completed','demo') for v in values),'interrupted':interrupted,'pending':sum(v['status'] in ('unverified','deferred') for v in values),'items':values[-100:]})
            except Exception:continue
        return sorted(result,key=lambda x:x['time'],reverse=True)[:30]
    def _notify(self):
        self.history=self._history()
        if self.on_finish:
            try:self.on_finish(self.snapshot())
            except Exception as exc:
                with self.lock:self.state['persistence_error']=str(exc)

    def external(self,title,fn):
        path=self.directory/f'action-{time.time_ns()}.jsonl'
        def write(status,message,verification=None):
            row={'time':now(),'index':0,'title':title,'status':status,'message':message}
            if verification:row['verification']=verification
            with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
            with self.lock:self.history=self._history();self.revision+=1
        write('running','Выполняется действие')
        try:
            result=fn();verification=result.get('verification') if isinstance(result,dict) else None
            status='demo' if self.demo else 'success' if verification=='confirmed' else 'completed'
            message='Демонстрация: Windows не изменялась.' if self.demo else (result.get('message') if isinstance(result,dict) else None) or 'Команда завершена. Состояние можно перечитать в соответствующем разделе.'
            write(status,message,verification);return result
        except Exception as e:
            write('error',str(e)[:1600]);raise

    def resolve_check(self,ident,check):
        """Update the original journal, without executing the original command."""
        with self.lock:
            pending=next((r for r in self.pending.snapshot() if r['id']==ident),None)
            if not pending:raise ValueError('Проверка уже закрыта')
            op=pending['operation'];status=check.get('status')
            if status not in ('confirmed','closed','unverified','deferred','rejected'):raise ValueError('Неизвестный результат проверки')
            outcome={'confirmed':'success','rejected':'error'}.get(status,status)
            origin=op.get('_journal');index=op.get('_index')
            if isinstance(origin,str) and __import__('re').fullmatch(r'apply-[0-9]+\.jsonl',origin) and type(index)==int and 0<=index<2000:
                path=self.directory/origin
                if path.is_file() and not path.is_symlink() and path.stat().st_size<=2097152:
                    from .pending import fingerprint
                    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
                    old=next((r for r in reversed(rows) if r.get('index')==index),None)
                    if old and fingerprint(old)==fingerprint(op):
                        row={**old,'time':now(),'status':outcome,'verification':status,'message':str(check.get('message',''))[:2000]}
                        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                        if self.state.get('log')==str(path) and index<len(self.state['items']):self.state['items'][index].update(status=outcome,verification=status,message=row['message'])
            if status in ('confirmed','closed'):self.pending.remove(ident)
            else:self.pending.add(op,status if status in ('unverified','deferred') else 'unverified',check.get('message',''))
            self.history=self._history();self.revision+=1
            return {**check,'operation':copy.deepcopy(op),'id':ident}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({**self.state,'pending_checks':self.pending.snapshot(),'pending_warning':self.pending.warning,'undo_groups':[{'id':g['id'],'time':g['time'],'count':len(g['entries']),'kinds':sorted(set(v['kind'] for v in g['entries']))} for g in self.undo_groups]})
    def record(self,index,status,message=''):
        with self.lock:
            self.revision+=1
            self.state['items'][index]['status']=status; self.state['items'][index]['message']=message
            row={'time':now(),'index':index,'title':self.state['items'][index]['title'],'status':status,'message':message}
            for key in ('details','error_code','verification','kind','key','value','orientation','adapter'):
                if key in self.state['items'][index]:row[key]=self.state['items'][index][key]
            try:
                with self.logfile.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
                return True
            except OSError as exc:
                self.state['persistence_error']=str(exc);return False
    def start(self,plan,info,updates):
        plan=validate_plan(plan,info,updates,demo=self.demo)
        ops=operations(plan,info,updates)
        if not ops: raise ValueError('Не выбрано ни одного изменения')
        if any(self.pending.contains(op) for op in ops):raise ValueError('Это действие уже выполнялось и ожидает проверки. Сначала проверьте его результат в истории.')
        with self.lock:
            if self.state['running']: raise ValueError('Применение уже идёт')
            self.pending.require_capacity(ops)
            self.cancel.clear();self.stop_reason='Остановлено пользователем'
            self.logfile=self.directory/f'apply-{time.time_ns()}.jsonl'
            self.logfile.touch(exist_ok=False);self.active_undo_id=self.logfile.stem
            self.state={'running':True,'finished':False,'reboot':False,'can_undo':False,'log':str(self.logfile),
                        'items':[dict(x,status='queued',message='') for x in ops]}
        for i in range(len(ops)):
            if not self.record(i,'queued'):
                with self.lock:self.state['running']=False;self.state['finished']=True
                raise OSError('Не удалось сохранить журнал; настройки не запускались')
        threading.Thread(target=self._run,args=(ops,info),daemon=True).start()
    def _run(self,ops,info):
        power_failed=False;packages_failed=False;driver_safety_failed=False
        self.backend.progress=self.set_stage;self.backend.cancel_event=self.cancel
        try:
            for i,op in enumerate(ops):
                if self.cancel.is_set(): self.record(i,'skipped',getattr(self,'stop_reason','Остановлено пользователем')); continue
                if driver_safety_failed and op['kind']=='update':
                    self.record(i,'skipped','Копия драйверов не создана. Обновления не запускались.');continue
                if packages_failed and op['kind'] in ('app','upgrade'):
                    self.record(i,'skipped','Не удалось подготовить установку. Повторите подготовку в разделе программ.');continue
                if power_failed and op['key'] in ['screen_ac','screen_dc','sleep_ac','sleep_dc']:
                    self.record(i,'skipped','Выбранная схема питания не включилась'); continue
                if not self.record(i,'running'):
                    self.cancel.set();continue
                self.set_stage({'package_manager':'Подготовка установки программ','app':'Загрузка и установка программы','upgrade':'Загрузка и обновление программы','update':'Проверка, загрузка и установка обновления','display':'Проверка режима экрана','restore_point':'Создание точки восстановления'}.get(op['kind'],'Применение настройки')+' · '+op['title'])
                try:
                    if self.demo:
                        time.sleep(.12); message='Демонстрация: система не изменена'
                        if hasattr(self.backend,'apply_demo'):self.backend.apply_demo(op)
                    else:
                        message=self._apply(op,info)
                    outcome='success'
                    if not self.demo and hasattr(self.backend,'verify_operation'):
                        check=self.backend.verify_operation(op)
                        with self.lock:self.state['items'][i]['verification']=check['status']
                        if check['status']=='rejected':raise RuntimeError(check['message'])
                        if check['status'] in ('unverified','deferred'):
                            outcome=check['status'];op.update(_journal=self.logfile.name,_index=i);self.pending.add(op,outcome,check['message'])
                        message=(message or 'Команда выполнена')+'. '+check['message']
                    self.record(i,outcome,message or 'Готово')
                except Exception as exc:
                    if op['key']=='power_plan': power_failed=True
                    if op['kind']=='driver_safety':driver_safety_failed=True
                    if op['kind']=='restore_point':self.stop_reason='Точка восстановления не создана; очередь остановлена';self.cancel.set()
                    from .packages import SetupError,UserCancelled
                    if op['kind']=='package_manager' or isinstance(exc,SetupError):packages_failed=True
                    details=getattr(exc,'details','')
                    with self.lock:
                        if details:self.state['items'][i]['details']=details
                        if getattr(exc,'code',None) is not None:self.state['items'][i]['error_code']=f"0x{exc.code:08X}"
                    if isinstance(exc,UserCancelled):self.cancel.set();self.record(i,'skipped',str(exc))
                    else:self.record(i,'error',str(exc)[:1600])
        finally:
            self.backend.progress=lambda text:None;self.backend.cancel_event=None
            self.backend.display_guard.restore_pending()
            with self.lock:
                self.state['can_undo']=bool(self.undo);self.state['stage']=''
            self._notify()
            with self.lock:self.state['running']=False;self.state['finished']=True
    def _apply(self,op,info):
        b=self.backend; kind,key,value=op['kind'],op['key'],op['value']
        if kind=='package_manager':return b.prepare_package_manager()['message']
        if kind=='restore_point':
            op['sequence']=b.restore_point(); return 'Точка создана. Программы и обновления автоматически не откатываются.'
        if kind=='setting':
            saved=None
            if key in REG: saved={'kind':'registry','values':b.reg_snapshot(key)}
            elif key=='mouse_accel':
                from .native import get_mouse_params
                saved={'kind':'mouse_params','value':get_mouse_params()}
            elif key in __import__('winpilot.native',fromlist=['NATIVE_KEYS']).NATIVE_KEYS:
                from .native import read_input
                current=read_input()
                if key in current: saved={'kind':'setting','key':key,'value':current[key]}
            elif key in ['power_plan','screen_ac','screen_dc','sleep_ac','sleep_dc']:
                # Read again: previous selected scheme may have changed timeouts.
                if key=='power_plan':
                    match=__import__('re').search(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}',b.run(['powercfg.exe','/getactivescheme']))
                    if match: saved={'kind':'setting','key':key,'value':match.group()}
                else:
                    option='VIDEOIDLE' if key.startswith('screen') else 'STANDBYIDLE'
                    subgroup='SUB_VIDEO' if key.startswith('screen') else 'SUB_SLEEP'
                    vals=__import__('re').findall(r'0x([0-9a-fA-F]{8})',b.run(['powercfg.exe','/query','SCHEME_CURRENT',subgroup,option]))
                    if len(vals)>=2: saved={'kind':'power_seconds','key':key,'value':str(int(vals[-2 if key.endswith('ac') else -1],16)),'scheme':b.active_power_scheme() if hasattr(b,'active_power_scheme') else None}
            elif key=='time_zone':saved={'kind':'setting','key':key,'value':b.psjson('[TimeZoneInfo]::Local.Id|ConvertTo-Json -Compress')}
            elif key=='layouts':
                saved={'kind':'languages','value':b.psjson("@{languages=@(Get-WinUserLanguageList | Select-Object LanguageTag,InputMethodTips); tip=(Get-WinDefaultInputMethodOverride).InputMethodTip} | ConvertTo-Json -Depth 6 -Compress")}
            elif key=='dns':
                saved={'kind':'dns','adapter':op['adapter'],'value':b.psjson("$v=Get-DnsClientServerAddress -InterfaceIndex $p.id -AddressFamily IPv4; $a=Get-NetAdapter -InterfaceIndex $p.id; if($p.guid -and ([guid]$a.InterfaceGuid) -ne ([guid]$p.guid)){throw 'Сетевой адаптер изменился; повторите сканирование'}; $path='HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\'+([guid]$a.InterfaceGuid).ToString('B'); $n=(Get-ItemProperty -LiteralPath $path -Name NameServer -ErrorAction SilentlyContinue).NameServer; @{guid=[string]$a.InterfaceGuid; servers=@($v.ServerAddresses); auto=[string]::IsNullOrWhiteSpace($n)} | ConvertTo-Json -Compress",{'id':op['adapter'],'guid':next(n.get('guid','') for n in info['network'] if n['id']==op['adapter'])})}
            # Save BEFORE mutating, including partially failed multi-value operations.
            if saved: self._save_undo(saved)
            b.apply_setting(key,value,op.get('adapter'))
            return 'Применено. Для части параметров оболочки нужен новый вход в Windows.' if key in REG else 'Применено'
        if kind=='brightness':
            old=b.get_brightness(key)
            self._save_undo({'kind':'brightness','key':key,'value':old}); b.brightness(key,value); return
        if kind=='audio_default':
            from .profile_audio import read_default,set_role
            old=read_default(value['flow'],value['role'])
            if old==key:return 'Устройство уже выбрано'
            self._save_undo({'kind':'audio_default','key':key,'value':old,'flow':value['flow'],'role':value['role']})
            try:set_role(key,value['flow'],value['role'])
            except Exception as exc:
                try:set_role(old,value['flow'],value['role'])
                except Exception:
                    raise ValueError('Переключение звука не завершено. Возврат прежнего устройства тоже не подтверждён; проверьте звук в Windows.') from exc
                raise ValueError('Не удалось переключить звук. Прежнее устройство возвращено.') from exc
            return 'Основное устройство звука выбрано'
        if kind=='audio':
            from .audio import get_endpoint,set_endpoint
            self._save_undo({'kind':'audio','key':key,'value':get_endpoint(key)})
            set_endpoint(key,value.get('volume'),value.get('mute')); return 'Звук настроен'
        if kind=='languages':
            self._save_undo({'kind':'languages','value':b.psjson("@{languages=@(Get-WinUserLanguageList | Select-Object LanguageTag,InputMethodTips); tip=(Get-WinDefaultInputMethodOverride).InputMethodTip} | ConvertTo-Json -Depth 6 -Compress")})
            b.set_languages(value);return 'Список языков сохранён; существующие методы ввода сохранены'
        if kind=='startup':
            row=next((r for r in b.startup() if r['id']==key and r.get('controllable')),None)
            if row is None:raise ValueError('Запись автозагрузки изменилась')
            self._save_undo({'kind':'startup','key':key,'value':row['enabled']})
            b.set_startup(key,value);return 'Автозагрузка изменена'
        if kind in ('app','upgrade'):
            result=b.install_app(key) if kind=='app' else b.upgrade_app(key)
            if isinstance(result,dict):
                if result.get('reboot'):
                    op['installer_reboot']=True
                    with self.lock:self.state['reboot']=True
                return result.get('message','Установка завершена')
            return result
        if kind=='driver_safety':
            from .driver_safety import create
            result=create(b);op['backup_path']=result['path']
            with self.lock:self.state['driver_backup']=result['path']
            return result['message']
        if kind=='update':
            result=b.install_update(key,value)
            op['reboot']=bool(result.get('reboot'))
            if result.get('reboot'):
                with self.lock: self.state['reboot']=True
            return result.get('message','Установлено')
        if kind=='layout':
            ident=b.display_guard.apply_layout(value)
            if not b.display_guard.wait(ident):raise RuntimeError('Схема не подтверждена; отправлена команда возврата')
            return 'Расположение экранов подтверждено'
        if kind=='display':
            ident=b.display_guard.apply(key,value,op['orientation'])
            if not b.display_guard.wait(ident): raise RuntimeError('Режим не подтверждён; отправлена команда возврата прежнего режима')
            return 'Новый режим подтверждён и сохранён'
        raise ValueError('Неизвестная операция')
    def set_stage(self,text):
        with self.lock:self.state['stage']=str(text)[:300];self.revision+=1
    def _save_undo(self,value):
        ident=self.active_undo_id or 'legacy'
        group=next((g for g in self.undo_groups if g['id']==ident),None)
        if group is None:
            if len(self.undo_groups)>=50:raise RuntimeError('Достигнут предел сохранённых откатов. Сначала верните старые настройки.')
            group={'id':ident,'time':now(),'entries':[]};self.undo_groups.append(group)
        if len(self.undo)>=2000:raise RuntimeError('Слишком много сохранённых значений для отката')
        group['entries'].append(value);self.undo.append(value);self._persist_undo()
    def _persist_undo(self):
        from .workspace import atomic_json
        atomic_json(self.directory/'last-settings-backup.json',{'version':2,'groups':self.undo_groups})
    def retry_persistence(self):
        with self.lock:
            if self.state['running']:raise ValueError('Дождитесь завершения применения')
            self._persist_undo()
            if self.state.get('log'):
                rows=[{'time':now(),'index':i,'title':v['title'],'status':v['status'],'message':v.get('message',''),**{k:v[k] for k in ('details','error_code','verification','kind','key','value','orientation','adapter') if k in v}} for i,v in enumerate(self.state['items'])]
                path=Path(self.state['log']);text=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
                with path.open('w',encoding='utf-8') as f:f.write(text);f.flush();os.fsync(f.fileno())
            self.state.pop('persistence_error',None);self.revision+=1
        self._notify()
        if self.state.get('persistence_error'):raise OSError(self.state['persistence_error'])
    def undo_entries(self,group_id=None):
        if not self.undo_groups:return []
        group=next((g for g in self.undo_groups if g['id']==group_id),None) if group_id else self.undo_groups[-1]
        if group is None:raise ValueError('Группа отката недоступна')
        if group is not self.undo_groups[-1]:raise ValueError('Сначала верните более поздние изменения, чтобы сохранить порядок настроек')
        return group['entries']
    def start_undo(self,group_id=None):
        with self.lock:
            if self.state['running']:raise ValueError('Дождитесь окончания применения')
            entries=self.undo_entries(group_id)
            if not entries:raise ValueError('Нет настроек для отката')
            self.undoing_id=next(g['id'] for g in self.undo_groups if g['entries'] is entries)
            values=list(reversed(entries));self.cancel.clear()
            self.logfile=self.directory/f'undo-{time.time_ns()}.jsonl';self.logfile.touch(exist_ok=False)
            self.state={'running':True,'finished':False,'reboot':False,'can_undo':False,'log':str(self.logfile),'items':[{'title':f'Вернуть настройку {v.get("key",v["kind"])}','status':'queued','message':''} for v in values]}
        for i in range(len(values)):
            if not self.record(i,'queued'):
                self.state['running']=False;raise OSError('Не удалось сохранить журнал отката')
        threading.Thread(target=self._undo,args=(values,),daemon=True).start()
    def _undo(self,values):
        failed=[]
        try:
            for i,v in enumerate(values):
                if not self.record(i,'running'):
                    failed.extend(values[i:]);break
                try:
                    b=self.backend
                    if v['kind']=='registry': b.restore_registry(v['values'])
                    elif v['kind']=='mouse_params':
                        from .native import set_mouse_params
                        set_mouse_params(v['value'])
                    elif v['kind']=='setting': b.apply_setting(v['key'],v['value'])
                    elif v['kind']=='power_seconds':
                        suffix='ac' if v['key'].endswith('ac') else 'dc'
                        subgroup='SUB_VIDEO' if v['key'].startswith('screen') else 'SUB_SLEEP'
                        setting='VIDEOIDLE' if v['key'].startswith('screen') else 'STANDBYIDLE'
                        b.run(['powercfg.exe',f'/set{suffix}valueindex',v.get('scheme') or 'SCHEME_CURRENT',subgroup,setting,v['value']])
                        b.run(['powercfg.exe','/setactive',b.active_power_scheme() if hasattr(b,'active_power_scheme') else 'SCHEME_CURRENT'])
                    elif v['kind']=='audio_default':
                        from .profile_audio import read_default,set_role
                        current=read_default(v['flow'],v['role'])
                        if current not in (v['key'],v['value']):raise ValueError('Выбор звука уже изменён вне профиля. Автоматический возврат отменён.')
                        set_role(v['value'],v['flow'],v['role'])
                    elif v['kind']=='audio':
                        from .audio import set_endpoint
                        set_endpoint(v['key'],mute=v['value']['mute'],scalar=v['value']['scalar'])
                    elif v['kind']=='startup':b.set_startup(v['key'],v['value'])
                    elif v['kind']=='brightness': b.brightness(v['key'],v['value'])
                    elif v['kind']=='dns': b.restore_dns(v)
                    elif v['kind']=='languages': b.ps("$l=New-WinUserLanguageList $p.value.languages[0].LanguageTag; $l.Clear(); foreach($lang in $p.value.languages){$entry=(New-WinUserLanguageList $lang.LanguageTag)[0]; $entry.InputMethodTips.Clear(); foreach($tip in $lang.InputMethodTips){$entry.InputMethodTips.Add([string]$tip)}; $l.Add($entry)}; Set-WinUserLanguageList $l -Force; if($p.value.tip){Set-WinDefaultInputMethodOverride -InputTip $p.value.tip}else{Set-WinDefaultInputMethodOverride}",v)
                    check=b.verify_undo(v) if hasattr(b,'verify_undo') else None
                    if check and check['status']!='confirmed':raise RuntimeError(check['message'])
                    self.record(i,'success',check['message'] if check else 'Возвращено')
                except Exception as exc:
                    failed.append(v); self.record(i,'error',str(exc)[:1500])
        finally:
            with self.lock:
                for g in self.undo_groups:
                    if g['id']==self.undoing_id:g['entries']=list(reversed(failed))
                self.undo_groups=[g for g in self.undo_groups if g['entries']]
                self.undo=[v for g in self.undo_groups for v in g['entries']];self.state['can_undo']=bool(self.undo)
            try:self._persist_undo()
            except Exception as exc:
                with self.lock:self.state['persistence_error']=str(exc)
            self._notify()
            with self.lock:self.state['running']=False;self.state['finished']=True
