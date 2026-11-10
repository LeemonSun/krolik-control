"""Loopback-only desktop UI server with a per-launch capability token."""
import copy
import hashlib
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .catalog import SETTINGS, APPS, LINKS, ACTIONS, PRESETS
from .workspace import Workspace
from .version import VERSION, AUTHOR
from .engine import Engine, validate_plan, operations

MUTATION_TASKS={'archive_action','driver_vendor_action','audio_default','storage_clean','firmware_action','software_action','mixer_action','startup_tasks_action','display_advanced_apply'}

class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Повторяющийся ключ JSON')
        result[key] = value
    return result


def invalid_json_constant(value):
    raise ValueError('Недопустимое число JSON')

class Application:
    def __init__(self,backend,ui,directory,demo=False):
        self.backend=backend; self.ui=Path(ui); self.demo=demo; self.token=secrets.token_urlsafe(32)
        self.lock=threading.RLock(); self.info=None; self.tasks={}; self.data={}; self.last_seen=time.monotonic()
        self.window_tag=secrets.token_hex(4);self.desktop=None;self.desktop_sequence=0
        self.workspace=Workspace(directory);self.workspace_revision=0
        self.backend.directory=Path(directory);self.engine=Engine(backend,directory,demo);self.engine.on_finish=self._finished; self.http=None;self.close_requested=False;self.activation=0;self.window_leave=None;self.data_revision=0;self.lifetime_connections=0
        from .care import CareCenter
        self.care=CareCenter(self);self.care.publish()
        from .pc import PcCenter
        self.pc=PcCenter(self)
        from .firmware import FirmwareCenter
        self.firmware=FirmwareCenter(self,directory)
        from .storage import StorageCenter
        self.storage=StorageCenter(self)
        from .audio_routing import AudioRouter
        self.audio_router=AudioRouter(self,directory)
        from .startup_tasks import StartupTasks
        self.startup_tasks=StartupTasks(self,directory)
        from .mixer import Mixer
        self.mixer=Mixer(self,directory)
        from .software import SoftwareCenter
        self.software=SoftwareCenter(self)
        from .toolbox import Toolbox
        self.toolbox=Toolbox(self,directory)
        from .driver_sources import DriverSources
        self.driver_sources=DriverSources(self,directory)
        from .archives import ArchiveCenter
        self.archives=ArchiveCenter(self)
    def _finished(self,result):
        with self.lock:
            self.last_result=copy.deepcopy(result)
            if result.get('log') and '/undo-' not in result['log'].replace('\\','/'):
                try:self.workspace.clear_successes(result['items']);self.workspace_revision+=1
                except Exception:
                    if self.info:self._queue_refresh(result)
                    raise
                done={i['key'] for i in result['items'] if i.get('kind')=='update' and i.get('status')=='success'}
                for name in ('driver_updates','software_updates'):
                    self.data[name]=[u for u in self.data.get(name,[]) if u['id'] not in done]
            if self.info:self._queue_refresh(result)
    def _queue_refresh(self,result):
        # Reserve readback before Engine exposes an idle state to other actions.
        if self.tasks.get('refresh',{}).get('status')=='running':return
        self.tasks['refresh']={'status':'running','started':time.time()}
        threading.Thread(target=self._refresh_after_run,args=(result,),daemon=True).start()
    def _refresh_after_run(self,result=None):
        while self.engine.snapshot()['running']:time.sleep(.05)
        try:
            self.scan_inventory()
            kinds={i.get('kind') for i in (result or {}).get('items',[]) if i.get('status') in ('success','error')}
            if 'update' in kinds:self.task('drivers',self.backend.drivers)
            if kinds&{'app','upgrade','package_manager'} and hasattr(self.backend,'programs'):self.task('programs',getattr(self.backend,'local_programs',self.backend.programs))
            if 'startup' in kinds and hasattr(self.backend,'startup'):self.task('startup',self.backend.startup)
        except ValueError:pass
        finally:
            with self.lock:self.tasks.pop('refresh',None)
    def leave_window(self,body):
        if not self.engine.snapshot()['running'] and 'workspace' in body and body.get('revision')==self.workspace_revision:
            try:self.workspace.save(body['workspace']);self.workspace_revision+=1
            except Exception as exc:self.workspace.warning='Последний выбор не сохранён: '+str(exc)
        marker=time.monotonic();self.window_leave=marker
        def close_if_gone():
            time.sleep(1.8)
            if self.last_seen>marker or self.window_leave!=marker or self.lifetime_connections:return
            self.engine.cancel.set();self.care.stop();self.toolbox.stop();self.toolbox.power.close();self.backend.display_guard.restore_pending()
            while self.engine.snapshot()['running'] or self.care.state['running'] or self.toolbox.state['running'] or self.mutation_running():time.sleep(.2)
            if self.last_seen>marker or self.lifetime_connections:return
            self.close_requested=True
            if self.http:self.http.shutdown()
        threading.Thread(target=close_if_gone,daemon=True).start()
    def catalog(self):
        result=[]
        native_items=[('text-tools','Текст и пароли','JSON, кодирование и генератор паролей','json base64 url пароль password текст'),('tools','Инструменты','Файлы, процессы, сеть и проверка устройств','инструменты папки размер дубликаты sha256 процессы wifi smart nvme батарея защита принтер'),('storage','Место на дисках','Свободное место и очистка старых временных файлов','диск очистка место temp временные файлы'),('firmware','BIOS и память','Профили памяти, UEFI, защита и настройки производителя','биос bios uefi xmp expo разгон память частота оперативка tpm secure boot'),('pc','Мой ПК','Комплектующие, схема рабочего места, нагрузка и датчики','компьютер железо cpu gpu память диски температура нагрузка'),('care','Проверка и исправление','Звук, микрофон, интернет, нагрузка, бенчмарк и восстановление','диагностика скорость тест голос шум нет звука тормозит fps benchmark'),('monitor','Мониторы: разрешение и частота','Все режимы подключённых экранов','герцовка герцы hz refresh 144 180 240 ориентация разрешение'),('sound','Громкость динамиков и микрофона','Подключённые аудиоустройства','звук наушники колонки микрофон громкость'),('drivers','Драйверы устройств','Поиск и установка подходящих обновлений','оборудование принтер usb видеокарта драйвер'),('startup','Автозагрузка программ','Управление программами при входе','автозапуск startup run'),('diagnostics','Диагностика сети','Проверка DNS и соединения','интернет сеть dns tcp'),('preferences','Настройки приложения','Тема и размер интерфейса','масштаб тема плотность'),('system','Обновления Windows','Поиск, загрузка и установка','windows update обновление')]
        native_items.insert(0,('archives','ZIP-архивы','Создание, просмотр и распаковка ZIP','zip архив распаковка упаковка'))
        for page,title,description,tags in native_items:
            result.append(dict(id='page:'+page,kind='device',group=page,title=title,description=description,tags=tags,available=bool(self.info),reason='',advanced=False))
        for s in self.settings():
            result.append(dict(id='setting:'+s['key'],kind='setting',group=s['group'],title=s['title'],description=s['description'],tags=s['key'],available=s['enabled'],reason=s['reason'],advanced=s['advanced']))
        for key,(title,group) in APPS.items():result.append(dict(id='app:'+key,kind='app',group='apps',title=title,description=group+' · установка в приложении',tags=key,available=bool(self.info and int(self.info.get('build','0'))>=17763),reason='Нужна Windows 10 1809 или новее',advanced=False))
        return result
    def scan_inventory(self):
        if hasattr(self.backend,'quick_inventory'):self.task('inventory',self.backend.quick_inventory)
        else:self.task('inventory',self.backend.inventory)
    def blocking_scan(self):
        return any(t.get('status')=='running' for name,t in self.tasks.items() if name not in ('inventory_details','drivers','activation'))
    def mutation_running(self):
        return any(self.tasks.get(name,{}).get('status')=='running' for name in MUTATION_TASKS)
    def task(self,name,fn):
        with self.lock:
            if hasattr(self,'care') and self.care.state['running']:raise ValueError('Дождитесь завершения диагностики')
            if self.engine.snapshot()['running'] and name!='inventory_details': raise ValueError('Дождитесь окончания применения')
            if name in ('audio_test','audio_meter','voice_playback') and any(self.tasks.get(key,{}).get('status')=='running' for key in ('audio_test','audio_meter','voice_playback')):raise ValueError('Звуковая проверка уже идёт. Дождитесь её окончания.')
            if self.tasks.get(name,{}).get('status')=='running': return
            if name in ['driver_updates','software_updates'] and any(self.tasks.get(x,{}).get('status')=='running' for x in ['driver_updates','software_updates']): raise ValueError('Поиск обновлений уже идёт; дождитесь завершения')
            self.tasks[name]={'status':'running','started':time.time()}
        def run():
            start=time.monotonic()
            try:
                titles={'archive_action':'Работа с ZIP','driver_vendor_action':'Запуск установщика производителя','audio_default':'Основное устройство звука','storage_clean':'Очистка временных файлов','firmware_action':'Изменение BIOS','software_action':'Действие с установленной программой','mixer_action':'Громкость приложения','startup_tasks_action':'Автозапуск задачи','display_advanced_apply':'Параметры экранов'}
                result=self.engine.external(titles[name],fn) if name in titles else fn()
                with self.lock:
                    if name=='inventory':
                        self.info=result
                        for item in ('programs','startup'):
                            if item in self.data:self.info[item]=self.data[item]
                    elif name in ('devices','inventory_details'):
                        self.info['settings'].update(result.pop('settings',{}));self.info.update(result)
                    else:
                        if name=='drivers':
                            from .hardware import ordered_devices
                            result=ordered_devices(result)
                        self.data[name]=result
                        if name in ('programs','startup') and self.info:self.info[name]=result
                        if name=='programs' and self.info and hasattr(self.backend,'package_manager'):self.info['winget']=self.backend.package_manager.available_hint()
                    self.tasks[name]={'status':'done','seconds':round(time.monotonic()-start,2),'finished':time.time()}
                    self.data_revision+=1
                    if name=='inventory' and hasattr(self.backend,'inventory_details'):self.task('inventory_details',self.backend.inventory_details)
            except Exception as exc:
                messages={'inventory':'Не удалось определить компьютер. Повторите проверку.','inventory_details':'Не удалось прочитать часть параметров. Повторите проверку.','firmware':'Не удалось прочитать BIOS. Обновите сведения или запустите приложение от имени администратора.','firmware_action':'Не удалось завершить действие BIOS. Обновите сведения и проверьте сохранённый результат.','programs':'Не удалось проверить программы. Повторите проверку.','drivers':'Не удалось прочитать список устройств. Повторите проверку.','driver_updates':'Не удалось найти обновления драйверов. Проверьте интернет и повторите.','software_updates':'Не удалось проверить обновления Windows. Проверьте интернет и повторите.','audio_meter':'Не удалось проверить микрофон. Проверьте его подключение и разрешение на использование.','audio_test':'Не удалось воспроизвести сигнал. Проверьте подключение устройства.','voice_playback':'Не удалось прослушать запись. Проверьте основной выход звука.'}
                with self.lock:
                    self.tasks[name]={'status':'error','error':str(exc) if name in ('firmware_action','audio_default','storage_clean','display_advanced_apply','software_action','software','verification','mixer','mixer_action','startup_tasks','startup_tasks_action') and isinstance(exc,ValueError) else messages.get(name,'Не удалось выполнить проверку. Повторите попытку.'),'details':(getattr(exc,'details','') or str(exc))[:6000]}
                    self.data_revision+=1
        threading.Thread(target=run,daemon=True).start()
    def updates(self):
        rows=copy.deepcopy(self.data.get('driver_updates',[])+self.data.get('software_updates',[]))
        for update in rows:
            hardware=str(update.get('hardware_id','')).casefold()
            update['device_ids']=[d['id'] for d in self.data.get('drivers',[]) if hardware and hardware in {str(v).casefold() for v in [d['id'],*d.get('hardware_ids',[]),*d.get('compatible_ids',[])]}]
        return rows
    def settings(self):
        result=[]
        for s in SETTINGS:
            choices=s.choices
            if s.key=='time_zone':choices={x['id']:x['name'] for x in (self.info or {}).get('time_zones',[])}
            if s.key=='power_plan': choices={x['id']:x['name'] for x in (self.info or {}).get('power_plans',[])}
            enabled=bool(self.info);reason=''
            if not self.info:reason='Сначала определите компьютер'
            if self.info and int(self.info.get('build',0))<s.min_build:enabled=False;reason='Недоступно в этой сборке Windows'
            if s.key in ('time_zone','power_plan') and not choices:enabled=False;reason='Windows не предоставила доступные значения'
            if s.key.endswith('_dc') and not (self.info or {}).get('battery'):enabled=False;reason='На этом ПК не обнаружена батарея'
            if s.key=='taskbar_align' and int((self.info or {}).get('build',0))<22000: enabled=False
            if s.group in (self.info or {}).get('pending_groups',[]):enabled=False;reason='Определяем доступные значения…'
            result.append(dict(key=s.key,group=s.group,title=s.title,description=s.description,choices=choices,admin=s.admin,enabled=enabled,reason=reason,advanced=s.advanced,min_build=s.min_build))
        return result
    def state_tag(self):
        with self.lock,self.engine.lock:
            tasks=[(name,t.get('status'),t.get('started'),t.get('seconds'),t.get('error')) for name,t in sorted(self.tasks.items())]
            job=self.engine.state
            signature=[self.toolbox.power.state(),self.activation,self.data_revision,tasks,self.workspace_revision,self.engine.revision,job['running'],job['finished'],job['reboot'],job['can_undo'],self.backend.display_guard.status()]
            return '"'+hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:24]+'"'
    def state(self):
        with self.lock:
            data=copy.deepcopy(self.data)
            data.setdefault('toolbox',copy.deepcopy(self.toolbox.state))['power']=self.toolbox.power.state()
            data['audio_default']={**data.get('audio_default',{}),**self.audio_router.status()}
            data['driver_sources']=self.driver_sources.sources()
            if 'driver_updates' in data:data['driver_updates']=[u for u in self.updates() if u.get('driver')]
            data['desktop']=self.desktop.snapshot() if self.desktop else {'available':False,'hotkeys':False,'conflicts':[]}
            return copy.deepcopy({'version':VERSION,'author':AUTHOR,'window_tag':self.window_tag,'activation':self.activation,'demo':self.demo,'info':self.info,'tasks':self.tasks,'data':data,
                    'settings':self.settings(),'apps':[{'id':k,'name':v[0],'group':v[1]} for k,v in APPS.items()],
                    'workspace':self.workspace.value,'workspace_revision':self.workspace_revision,'workspace_warning':self.workspace.warning or self.engine.recovery_warning,'catalog':self.catalog(),'presets':PRESETS,'history':self.engine.history,'engine':self.engine.snapshot(),'display_pending':self.backend.display_guard.status()})
    def post(self,path,body):
        if not isinstance(body,dict):raise ValueError('Некорректный запрос')
        if path=='/api/support/report':
            from .support_report import build
            return build(self)
        # Serialize task reservation and apply start so scans cannot race mutations.
        with self.lock:
            if self.mutation_running() and path not in ('/api/activate','/api/window/leave','/api/close','/api/workspace','/api/display/confirm','/api/cancel','/api/archive/cancel','/api/care/cancel','/api/tools/cancel'):
                raise ValueError('Дождитесь завершения текущего изменения')
            if self.toolbox.state['running'] and path not in ('/api/tools/cancel','/api/workspace','/api/window/leave','/api/activate','/api/display/confirm','/api/close'):raise ValueError('Дождитесь окончания инструмента или остановите его')
            if path=='/api/activate':
                self.activation+=1
                if hasattr(self.backend,'focus_window'):self.backend.focus_window()
                return {'ok':True}
            if path=='/api/driver-source/open':
                return self.driver_sources.open_source(body.get('vendor'))
            if path=='/api/archive/cancel':
                self.archives.cancel.set();return {'stopping':True}
            if path in ('/api/archive/preview','/api/archive/run'):
                if self.engine.snapshot()['running'] or self.care.state['running'] or any(t.get('status')=='running' for t in self.tasks.values()):
                    raise ValueError('Дождитесь завершения текущей операции')
                if path.endswith('/preview'):
                    self.task('archive_preview',lambda:self.archives.preview(body))
                else:
                    self.archives.cancel.clear()
                    self.task('archive_action',lambda:self.archives.run(body))
                return {'ok':True}
            if path=='/api/driver-source/cancel':
                self.driver_sources.cancel.set();return {'stopping':True}
            if path in ('/api/driver-source/download','/api/driver-source/launch'):
                if self.engine.snapshot()['running'] or self.care.state['running'] or any(t.get('status')=='running' for t in self.tasks.values()):
                    raise ValueError('Дождитесь завершения текущей операции')
                if path.endswith('/download'):
                    if body.get('confirmed') is not True:raise ValueError('Подтвердите загрузку установщика производителя')
                    vendor=body.get('vendor')
                    from .driver_sources import DOWNLOAD_HOSTS
                    if not isinstance(vendor,str) or vendor not in DOWNLOAD_HOSTS:raise ValueError('Неизвестный источник загрузки')
                    self.driver_sources.cancel.clear();self.data.pop('driver_download',None);self.data_revision+=1
                    self.task('driver_download',lambda:self.driver_sources.download(vendor))
                else:
                    self.task('driver_vendor_action',lambda:self.driver_sources.launch(body))
                return {'ok':True}
            if path=='/api/desktop/hide':
                if not self.desktop or not self.desktop.active:raise ValueError('Меню в трее пока недоступно')
                if self.engine.snapshot()['running'] or self.mutation_running():raise ValueError('Дождитесь завершения действия')
                if not self.desktop.focus(hide=True):raise ValueError('Не удалось свернуть окно')
                return {'ok':True}
            if path=='/api/window/leave':self.leave_window(body);return {'ok':True}
            if path=='/api/display/identify':
                ident=body.get('id')
                if ident not in {d['id'] for d in (self.info or {}).get('displays',[])}:raise ValueError('Монитор отключён')
                if not self.demo:self.task('identify',lambda:self.backend.identify_display(ident))
                return {'ok':True}
            if path=='/api/display/confirm':
                if type(body.get('keep'))!=bool or not isinstance(body.get('id'),str): raise ValueError('Некорректное подтверждение')
                return {'ok':self.backend.display_guard.resolve(body['id'],body['keep'])}
            if path=='/api/care/cancel':return {'stopping':self.care.stop()}
            if path=='/api/care/start':
                if self.engine.snapshot()['running'] or any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь завершения текущей операции')
                self.care.start(body.get('kind'),body);return {'ok':True}
            if path=='/api/care/backups':return {'backups':self.care.backups()}
            if path=='/api/care/preview':return self.care.preview(body.get('report'),body.get('finding'))
            if path=='/api/care/fix':
                if self.engine.snapshot()['running'] or any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь завершения текущей операции')
                return self.care.fix(body.get('token'))
            if path=='/api/care/forget-voice':
                if self.care.state['running'] or any(self.tasks.get(key,{}).get('status')=='running' for key in ('audio_test','audio_meter','voice_playback')):raise ValueError('Дождитесь окончания звуковой проверки')
                self.care.voice=None;self.care.state['voice_report']=None;self.care.publish();return {'ok':True}
            if path=='/api/care/undo':
                if self.engine.snapshot()['running'] or any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь окончания операции')
                return self.care.undo_last(body.get('report'))
            if path=='/api/care/voice':
                if self.demo:return {'ok':True,'message':'Демонстрация: звук не воспроизводился'}
                if self.care.state['running'] or self.engine.snapshot()['running']:raise ValueError('Дождитесь окончания операции')
                if not self.care.voice or body.get('report')!=self.care.state.get('voice_report'):raise ValueError('Запись больше не хранится в памяти. Запишите голос снова.')
                recording=self.care.voice
                self.task('voice_playback',lambda:__import__('winpilot.audio_tools',fromlist=['play_voice']).play_voice(recording));return {'ok':True}
            if path=='/api/care/open-backup':
                if self.demo:return {'ok':True}
                from .care_windows import driver_root
                root=driver_root();root.mkdir(parents=True,exist_ok=True);os.startfile(root);return {'ok':True}
            if path=='/api/cancel': self.engine.cancel.set(); return {'ok':True}
            if self.care.state['running'] and path not in ('/api/workspace','/api/window/leave','/api/activate'):raise ValueError('Дождитесь завершения диагностики или остановите её')
            if path=='/api/close':
                if self.mutation_running():raise ValueError('Дождитесь завершения текущего изменения')
                if self.toolbox.state['running']:
                    if not self.toolbox.stop():raise ValueError('Дождитесь завершения переименования')
                    raise ValueError('Инструмент останавливается. Закройте окно после завершения.')
                self.toolbox.power.close();self.driver_sources.cancel.set()
                if self.engine.snapshot()['running']:raise ValueError('Дождитесь завершения текущей операции')
                self.close_requested=True;return {'ok':True}
            if self.engine.snapshot()['running']: raise ValueError('Применение уже идёт')
            if path in ('/api/audio/test','/api/audio/meter'):
                channel=body.get('channel')
                if channel is not None and (type(channel)!=int or channel not in (0,1)):raise ValueError('Некорректный канал')
                ident=body.get('id');flow=0 if path.endswith('/test') else 1
                row=next((r for r in (self.info or {}).get('endpoints',[]) if r['id']==ident and r['flow']==flow),None)
                if row is None:raise ValueError('Аудиоустройство недоступно')
                def meter_update(value):
                    with self.lock:self.data['audio_meter']=value;self.data_revision+=1
                if self.demo:
                    def demo_audio():
                        if flow==0:return {'message':'Демонстрация: звук не воспроизводился'}
                        for i in range(16):meter_update({'id':ident,'peak':(i%5)/5,'maximum':.8,'running':True,'seconds':round((16-i)/2,1)});time.sleep(.5)
                        return {'id':ident,'peak':0,'maximum':.8,'running':False,'seconds':0,'message':'Демонстрационные данные; микрофон не включался'}
                    self.task('audio_test' if flow==0 else 'audio_meter',demo_audio)
                else:
                    from .audio_tools import test_output,meter_input
                    self.task('audio_test' if flow==0 else 'audio_meter',lambda:test_output(ident,channel) if flow==0 else meter_input(ident,meter_update))
                return {'ok':True}
            if path=='/api/elevate':
                if self.demo:return {'restarting':False,'message':'Демонстрация: права администратора не запрашиваются'}
                if (self.info or {}).get('admin'):return {'restarting':False,'message':'Приложение уже запущено с правами администратора'}
                if any(t['status']=='running' for t in self.tasks.values()):raise ValueError('Дождитесь завершения сканирования')
                self.backend.elevate(self.engine.directory)
                self.close_requested=True
                return {'restarting':True}
            if path=='/api/workspace':
                if type(body.get('revision'))!=int or body['revision']!=self.workspace_revision:raise ValueError('Выбор обновился. Дождитесь синхронизации и повторите действие.')
                value=self.workspace.save(body.get('workspace'));self.workspace_revision+=1
                return {'workspace':value,'revision':self.workspace_revision}
            if path=='/api/retry-save':
                self.engine.retry_persistence()
                return {'ok':True}
            if path=='/api/profile/validate':
                from .workspace import saved_plan
                return {'plan':saved_plan(body)}
            if path=='/api/startup-tasks/scan':self.task('startup_tasks',self.startup_tasks.scan);return {'ok':True}
            if path=='/api/startup-tasks/preview':return self.startup_tasks.preview(body)
            if path in ('/api/startup-tasks/apply','/api/startup-tasks/undo'):
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                def change_tasks():
                    result=self.startup_tasks.undo(body) if path.endswith('/undo') else self.startup_tasks.apply(body)
                    with self.lock:self.data['startup_tasks']=result
                    return result
                self.task('startup_tasks_action',change_tasks);return {'ok':True}
            if path=='/api/mixer/scan':self.task('mixer',self.mixer.scan);return {'ok':True}
            if path=='/api/mixer/preview':return self.mixer.preview(body)
            if path in ('/api/mixer/apply','/api/mixer/undo'):
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                def change_mixer():
                    result=self.mixer.undo(body) if path.endswith('/undo') else self.mixer.apply(body)
                    with self.lock:self.data['mixer']=result
                    return result
                self.task('mixer_action',change_mixer);return {'ok':True}
            if path=='/api/software/scan':self.task('software',self.software.scan);return {'ok':True}
            if path=='/api/software/preview':return self.software.preview(body)
            if path=='/api/software/apply':
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                job=self.software.consume(body)
                def change_software():
                    result=self.software.execute(job);inventory=result.pop('_inventory',None)
                    if inventory is not None:
                        with self.lock:
                            self.data['software']=inventory
                            if not self.demo and not inventory.get('notes'):
                                from .installed_apps import local_inventory
                                old={r['id']:r for r in self.data.get('programs',(self.info or {}).get('programs',[]))}
                                current=local_inventory(self.software.rows)
                                current=[old[r['id']] if r['id'] in old and old[r['id']].get('installations')==r['installations'] else r for r in current]
                                self.data['programs']=current
                                if self.info is not None:self.info['programs']=copy.deepcopy(current)
                    return result
                self.task('software_action',change_software);return {'ok':True}
            if path=='/api/tools/report':return self.toolbox.open_report(body.get('id'))
            if path=='/api/tools/preview':
                if self.engine.snapshot()['running'] or self.care.state['running'] or any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                self.toolbox.start('rename_preview',body);return {'ok':True}
            if path=='/api/tools/start':
                if self.engine.snapshot()['running'] or self.care.state['running'] or any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                self.toolbox.start(body.get('kind'),body);return {'ok':True}
            if path=='/api/tools/cancel':return {'stopping':self.toolbox.stop()}
            if path=='/api/power/start':
                if body.get('confirmed') is not True:raise ValueError('Подтвердите временный режим')
                r=self.toolbox.power.start(body.get('minutes'),body.get('display',False),self.demo);self.toolbox.publish();return r
            if path=='/api/power/stop':self.toolbox.power.close();self.toolbox.publish();return {'ok':True}
            if path=='/api/verification/check':
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                ident=body.get('id');row=next((r for r in self.engine.pending.snapshot() if r['id']==ident),None)
                if not row:raise ValueError('Проверка больше не ожидается')
                def reread():
                    check=self.backend.verify_operation(row['operation']) if not self.demo else {'status':'confirmed','message':'Демонстрация проверки'}
                    result=self.engine.resolve_check(ident,check)
                    if check['status']=='confirmed':
                        self.workspace.clear_successes([{**row['operation'],'status':'success'}]);self.workspace_revision+=1
                    return result
                self.task('verification',reread);return {'ok':True}
            if path=='/api/verification/dismiss':
                if self.engine.snapshot()['running'] or any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                if body.get('confirmed') is not True:raise ValueError('Подтвердите закрытие ожидания')
                self.engine.resolve_check(body.get('id'),{'status':'closed','message':'Ожидание закрыто пользователем. Результат не подтверждён.'});self.data_revision+=1;return {'ok':True}
            if path=='/api/scan':self.scan_inventory();return {'ok':True}
            if path=='/api/game/processes':
                def processes():
                    if self.demo:return [{'id':4242,'name':'Игра · пример','started':'demo'}]
                    from .game_capture import PROCESSES_PS
                    rows=self.backend.psjson(PROCESSES_PS,timeout=10)
                    return rows if isinstance(rows,list) else [rows] if isinstance(rows,dict) else []
                self.task('game_processes',processes);return {'ok':True}
            if path in ('/api/audio/default','/api/audio/default/undo'):
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь окончания операции')
                self.task('audio_default',lambda:self.audio_router.undo(body) if path.endswith('/undo') else self.audio_router.apply(body));return {'ok':True}
            if path=='/api/display/advanced/scan':
                def advanced_scan():
                    if self.demo:return [{'id':d['id'],'refresh_num':180000 if i==0 else 60000,'refresh_den':1000,'refresh_hz':180 if i==0 else 60,'hdr_available':i==0,'hdr_enabled':False,'bits':10,'hdr_reason':''} for i,d in enumerate((self.info or {}).get('displays',[]))]
                    from .display_advanced import inventory
                    return inventory()
                self.task('display_advanced',advanced_scan);return {'ok':True}
            if path=='/api/display/advanced/apply':
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь окончания операции')
                if body.get('confirmed') is not True or body.get('kind') not in ('hdr','topology'):raise ValueError('Подтвердите изменение экрана')
                if body['kind']=='hdr' and not any(d['id']==body.get('id') for d in (self.info or {}).get('displays',[])):raise ValueError('Экран отключён')
                if body['kind']=='topology' and body.get('topology') not in ('extend','clone','internal','external'):raise ValueError('Неизвестная схема')
                def advanced_apply():
                    if self.demo:return {'message':'Демонстрация: экран не менялся'}
                    ident=self.backend.display_guard.apply_advanced(body['kind'],body)
                    if not self.backend.display_guard.wait(ident):raise ValueError('Режим не подтверждён; выполнена попытка возврата')
                    try:
                        devices=self.backend.device_inventory()
                        from .display_advanced import inventory
                        extras=inventory()
                        with self.lock:
                            self.info.update(devices);self.data['display_advanced']=extras;self.data_revision+=1
                    except Exception:return {'verification':'confirmed','message':'Изменение подтверждено. Повторное чтение устройств пока недоступно.'}
                    return {'verification':'confirmed','message':'Изменение экрана подтверждено'}
                self.task('display_advanced_apply',advanced_apply);return {'ok':True}
            if path=='/api/storage/scan':
                self.task('storage',self.storage.scan);return {'ok':True}
            if path=='/api/storage/clean':
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь окончания проверки')
                snapshot=self.storage.consume(body)
                self.data.pop('storage',None);self.data_revision+=1
                self.task('storage_clean',lambda:self.storage.clean(snapshot));return {'ok':True}
            if path=='/api/firmware/scan':
                self.task('firmware',self.firmware.scan);return {'ok':True}
            if path=='/api/firmware/baseline':
                self.task('firmware',self.firmware.baseline);return {'ok':True}
            if path=='/api/firmware/preview':return self.firmware.preview(body)
            if path=='/api/firmware/apply':
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь текущей операции')
                intent=self.firmware.consume(body)
                self.task('firmware_action',lambda:self.firmware.execute(intent));return {'ok':True}
            if path=='/api/pc/refresh':return self.pc.read(refresh=True)
            if path=='/api/pc/inspect':
                kind=body.get('kind')
                if kind not in ('events','sleep'):raise ValueError('Неизвестная проверка')
                self.task('pc_'+kind,lambda:self.pc.inspect(kind));return {'ok':True}
            scans={
                '/api/devices/scan':('devices',self.backend.device_inventory),
                '/api/drivers':('drivers',self.backend.drivers),
                '/api/drivers/search':('driver_updates',lambda:self.backend.search_updates('Driver')),
                '/api/updates/search':('software_updates',lambda:self.backend.search_updates('Software')),
                '/api/activation':('activation',self.backend.activation),
            }
            scans.update({path:(name,getattr(self.backend,method)) for path,name,method in [('/api/programs','programs','local_programs' if hasattr(self.backend,'local_programs') else 'programs'),('/api/programs/updates','programs','programs'),('/api/startup','startup','startup'),('/api/network/test','network_test','network_test')] if hasattr(self.backend,method)})
            if path in scans:
                self.task(*scans[path]); return {'ok':True}
            if path in ['/api/preview','/api/apply']:
                if self.info is None: raise ValueError('Дождитесь сканирования ПК')
                if self.blocking_scan(): raise ValueError('Дождитесь завершения сканирования')
                p=validate_plan(body,self.info,self.updates(),demo=self.demo)
                ops=operations(p,self.info,self.updates())
                if path=='/api/apply': self.engine.start(p,self.info,self.updates())
                return {'operations':ops,'run':self.engine.snapshot().get('log') if path=='/api/apply' else None}
            if path=='/api/undo':
                if any(t.get('status')=='running' for t in self.tasks.values()):raise ValueError('Дождитесь завершения текущей операции')
                if any(v.get('kind')=='dns' for v in self.engine.undo_entries(body.get('group'))) and not self.demo and not ((self.info or {}).get('admin') or (self.info or {}).get('privileged_helper')):raise ValueError('Для возврата DNS нужны права администратора')
                self.engine.start_undo(body.get('group'));return {'ok':True}
            if path=='/api/open':
                key=body.get('id')
                if key not in LINKS: raise ValueError('Неизвестный раздел Windows')
                action=next((a for a in ACTIONS if a['link']==key),None)
                if action and (not self.info or int(self.info.get('build',0))<action['min_build']):raise ValueError('Раздел недоступен в этой сборке Windows')
                if self.demo: return {'ok':True,'message':'Демонстрация: раздел Windows не открывается'}
                os.startfile(LINKS[key]); return {'ok':True}
            raise ValueError('Неизвестное действие')

def create_server(app,port=0):
    class Handler(BaseHTTPRequestHandler):
        server_version='KrolikControl'
        sys_version=''
        def setup(self):
            super().setup()
            self.connection.settimeout(10)
        def log_message(self,*args): pass
        def send(self,status,body,kind='application/json; charset=utf-8',headers=None):
            data=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            for key,value in (headers or {}).items():self.send_header(key,value)
            self.end_headers(); self.wfile.write(data)
        def valid_host(self): return self.headers.get_all('Host')==[f'127.0.0.1:{self.server.server_port}']
        def authorized(self):
            origin=self.headers.get('Origin')
            tokens=self.headers.get_all('X-WinPilot-Token',[])
            return (self.valid_host() and len(self.headers.get_all('Origin',[]))<=1
                    and (not origin or origin==f'http://127.0.0.1:{self.server.server_port}')
                    and len(tokens)==1 and tokens[0].isascii()
                    and secrets.compare_digest(tokens[0],app.token))
        def do_GET(self):
            if not self.valid_host(): self.send(403,{'error':'Недопустимый Host'}); return
            path=urlsplit(self.path).path
            if path=='/api/lifetime':
                if not self.authorized():self.send(403,{'error':'Недействительный токен'});return
                with app.lock:
                    if app.lifetime_connections>=4 or app.close_requested:
                        self.send(429,{'error':'Слишком много открытых окон'});return
                    app.lifetime_connections+=1
                try:
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                    while not app.close_requested:
                        self.wfile.write(b': alive\n\n');self.wfile.flush();time.sleep(.5)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,OSError):pass
                finally:
                    with app.lock:
                        app.lifetime_connections-=1
                        if not app.lifetime_connections and not app.close_requested:app.leave_window({})
                return
            if path=='/api/state':
                if not self.authorized(): self.send(403,{'error':'Недействительный токен'}); return
                app.last_seen=time.monotonic();tag=app.state_tag()
                if self.headers.get('If-None-Match')==tag:self.send(304,b'',headers={'ETag':tag});return
                self.send(200,app.state(),headers={'ETag':tag});return
            if path=='/api/pc':
                if not self.authorized():self.send(403,{'error':'Недействительный токен'});return
                app.last_seen=time.monotonic();self.send(200,app.pc.read());return
            names={'/safety.js':'safety.js','/':'index.html','/app.js':'app.js','/style.css':'style.css','/theme.css':'theme.css','/hub.js':'hub.js','/favicon.ico':'favicon.ico','/navigation.js':'navigation.js','/rendering.js':'rendering.js','/desktop.js':'desktop.js','/desktop.css':'desktop.css','/brand.png':'brand.png','/maintenance.js':'maintenance.js','/display-layout.js':'display-layout.js','/languages.js':'languages.js','/care.js':'care.js','/care.css':'care.css','/pc.js':'pc.js','/pc.css':'pc.css','/firmware.js':'firmware.js','/firmware.css':'firmware.css','/peripherals.js':'peripherals.js','/product.js':'product.js','/product.css':'product.css','/release.js':'release.js','/release.css':'release.css'}
            names.update({name:name[1:] for name in ('/archives.js','/text-tools.js','/driver-sources.js','/polish.css','/locale.js','/locale-data.js','/modes.js','/modes.css','/krolik-mark.svg','/third-party-notices.json')})
            if path not in names: self.send(404,{'error':'Не найдено'}); return
            file=app.ui/names[path]
            self.send(200,file.read_bytes(),{'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','ico':'image/x-icon','png':'image/png','svg':'image/svg+xml','json':'application/json; charset=utf-8'}[file.suffix[1:]])
        def do_POST(self):
            if not self.authorized(): self.send(403,{'error':'Недействительный токен'}); return
            try:
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not lengths[0].isdigit() or self.headers.get_all('Transfer-Encoding'):
                    raise ValueError('Недопустимая длина запроса')
                length=int(lengths[0])
                limit=270336 if urlsplit(self.path).path in ('/api/workspace','/api/window/leave') else 131072
                if not 0<length<=limit: raise ValueError('Недопустимый размер запроса')
                if self.headers.get_content_type()!='application/json': raise ValueError('Ожидается JSON')
                if len(self.headers.get_all('Content-Type',[]))!=1:raise ValueError('Неоднозначный тип запроса')
                deadline=time.monotonic()+10;parts=[];remaining=length
                while remaining:
                    timeout=deadline-time.monotonic()
                    if timeout<=0:raise TimeoutError('Время запроса истекло')
                    self.connection.settimeout(min(5,timeout))
                    part=self.rfile.read1(min(65536,remaining))
                    if not part:raise ValueError('Запрос получен не полностью')
                    parts.append(part);remaining-=len(part)
                body=json.loads(b''.join(parts),object_pairs_hook=unique_json_object,parse_constant=invalid_json_constant)
                if not isinstance(body,dict): raise ValueError('Ожидается JSON-объект')
                result=app.post(urlsplit(self.path).path,body)
                self.send(200,result)
                if app.close_requested:threading.Thread(target=app.http.shutdown,daemon=True).start()
            except (TimeoutError,socket.timeout):self.send(408,{'error':'Время запроса истекло'})
            except (ValueError,TypeError,KeyError,RecursionError,json.JSONDecodeError) as exc: self.send(400,{'error':str(exc)[:1000]})
            except Exception as exc: self.send(500,{'error':str(exc)[:1200]})
    http=BoundedHTTPServer(('127.0.0.1',port),Handler)
    http.daemon_threads=True; app.http=http
    return http
