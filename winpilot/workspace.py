"""Atomic, bounded preferences and staged plans. Restoring never executes a plan."""
import copy
import json
import os
import re
import tempfile
import hashlib
import threading
from pathlib import Path
from .catalog import BY_KEY, APPS, ACTIONS

GUID=re.compile(r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')
PAGES={'archives','text-tools','tools','peripheral-test','storage','firmware','pc','overview','catalog','favorites','profiles','history','drivers','monitor','input','language','power','network','sound','appearance','gaming','privacy','apps','system','summary','preferences','startup','diagnostics','care'}
FAVORITES={*('setting:'+k for k in BY_KEY),*('app:'+k for k in APPS),*(a['id'] for a in ACTIONS),*('page:'+p for p in PAGES)}

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def ui_preferences(value):
    if not isinstance(value,dict) or set(value)-{'locale','zoom','motion','density','last_page','views','history','driver_targets','window','quick_keys'}:raise ValueError('Некорректные параметры интерфейса')
    result=copy.deepcopy(value)
    if type(result.get('quick_keys',False))!=bool:raise ValueError('Некорректная настройка горячих клавиш')
    if result.get('locale','ru') not in ('ru','en','de'):raise ValueError('Неизвестный язык интерфейса')
    if result.get('motion','system') not in ('system','off'):raise ValueError('Некорректная анимация')
    if result.get('zoom',100) not in (100,110,125,150) or type(result.get('zoom',100))!=int:raise ValueError('Неизвестный масштаб')
    if result.get('density','comfortable') not in ('comfortable','compact'):raise ValueError('Неизвестная плотность')
    if result.get('last_page','overview') not in PAGES:raise ValueError('Неизвестная страница')
    views=result.get('views',{})
    if not isinstance(views,dict) or set(views)-PAGES:raise ValueError('Некорректные страницы')
    for page,v in views.items():
        if not isinstance(v,dict) or len(json.dumps(v))>18000:raise ValueError('Состояние страницы слишком большое')
        if set(v)-{'scroll','monitor','catalogQuery','catalogGroup','catalogKind','appQuery','appGroup','driverQuery','driverFilter','driverCategory','driverMore','expanded','careTab','careMic','careSpeaker','careSelected','softwareTab','softwareQuery','toolTab','toolFind','toolReplace','toolExpected','toolHost','powerMinutes','powerDisplay'}:raise ValueError('Неизвестное состояние страницы')
        for k,x in v.items():
            if k=='scroll':
                if type(x) not in (int,float) or not 0<=x<=10000000:raise ValueError('Некорректная прокрутка')
            elif k=='powerMinutes':
                if type(x)!=int or x not in (15,30,60,120,360):raise ValueError('Некорректное время временного режима')
            elif k in ('driverMore','powerDisplay'):
                if type(x)!=bool:raise ValueError('Некорректный фильтр')
            elif k=='softwareTab':
                if x not in ('catalog','installed'):raise ValueError('Неизвестная вкладка программ')
            elif k=='toolTab':
                if x not in ('files','system','devices','network','transfer'):raise ValueError('Неизвестная вкладка инструментов')
            elif k=='careTab':
                if x not in ('audio','network','performance','recovery'):raise ValueError('Неизвестный раздел проверки')
            elif k=='expanded':
                if not isinstance(x,list) or len(x)>500 or any(not isinstance(i,str) or len(i)>1100 for i in x):raise ValueError('Некорректный список групп')
            elif x is not None and (not isinstance(x,str) or len(x)>1100):raise ValueError('Слишком длинный фильтр')
    hist=result.get('history',{'entries':['overview'],'index':0})
    if not isinstance(hist,dict) or set(hist)!={'entries','index'} or not isinstance(hist['entries'],list) or not 1<=len(hist['entries'])<=100 or any(p not in PAGES for p in hist['entries']) or type(hist['index'])!=int or not 0<=hist['index']<len(hist['entries']):raise ValueError('Некорректная история переходов')
    targets=result.get('driver_targets',[])
    if not isinstance(targets,list) or len(targets)>1000 or any(not isinstance(i,str) or not 1<=len(i)<=1024 for i in targets):raise ValueError('Некорректные устройства')
    window=result.get('window',{})
    if not isinstance(window,dict) or set(window)-{'left','top','width','height'}:raise ValueError('Некорректная геометрия окна')
    for k,x in window.items():
        low,high=(-32768,32768) if k in ('left','top') else (400,16384)
        if type(x)!=int or not low<=x<=high:raise ValueError('Некорректный размер окна')
    return result

def saved_plan(value):
    """Validate semantics against a virtual capability set; real hardware is checked before apply."""
    from .engine import validate_plan
    if not isinstance(value,dict) or len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>65536:raise ValueError('Профиль слишком большой или повреждён')
    p=copy.deepcopy(value)
    if not isinstance(p.get('settings',{}),dict):raise ValueError('Некорректные настройки')
    zone=p.get('settings',{}).get('time_zone')
    if zone is not None and (not isinstance(zone,str) or not re.fullmatch(r'[A-Za-z0-9 .()+_-]{1,150}',zone)):raise ValueError('Некорректный часовой пояс')
    scheme=p.get('settings',{}).get('power_plan')
    if scheme and (not isinstance(scheme,str) or not GUID.fullmatch(scheme)):raise ValueError('Некорректная схема питания')
    for key in ['displays','brightness','audio','audio_defaults','updates','apps','upgrades','startup','layout','languages']:
        if not isinstance(p.get(key,[]),list):raise ValueError('Некорректный список '+key)
    displays=p.get('displays',[])
    for d in displays:
        if not isinstance(d,dict) or not isinstance(d.get('id'),str) or len(d['id'])>512 or not isinstance(d.get('mode'),str) or not re.fullmatch(r'\d{2,5}x\d{2,5}@\d{2,4}',d['mode']):raise ValueError('Некорректный монитор')
    for key in ['brightness','audio']:
        for entry in p.get(key,[]):
            if not isinstance(entry,dict) or not isinstance(entry.get('id'),str) or not 1<=len(entry['id'])<=1024:raise ValueError('Некорректное устройство')
    for ident in p.get('updates',[]):
        if not isinstance(ident,str) or not GUID.fullmatch(ident):raise ValueError('Некорректный ID обновления')
    adapter=p.get('adapter')
    if adapter is not None and (type(adapter)!=int or not 0<adapter<2**31):raise ValueError('Некорректный сетевой адаптер')
    virtual=copy.deepcopy(p)
    if 'dns' in p.get('settings',{}) and adapter is None:virtual['adapter']=1
    info={'time_zones':[{'id':zone,'name':zone}] if zone else [],'build':'99999','admin':True,'battery':True,'winget':True,'power_plans':[{'id':scheme,'name':'Saved'}] if scheme else [],
          'network':[{'id':virtual.get('adapter',1)}],'language_options':[{'id':t} for t in p.get('languages',[])],
          'programs':[{'id':a,'installed':True,'update_available':True} for a in p.get('upgrades',[])],
          'startup':[{'id':r.get('id'),'controllable':True} for r in p.get('startup',[]) if isinstance(r,dict)],
          'displays':[{'id':d['id'],'modes':[{'id':d['mode']}]} for d in displays],
          'brightness':[{'id':b['id']} for b in p.get('brightness',[])],
          'endpoints':[{'id':a['id'],'controllable':True} for a in p.get('audio',[])]}
    for row in p.get('audio_defaults',[]):
        if not isinstance(row,dict):raise ValueError('Некорректное основное устройство звука')
        info['endpoints'].append({'id':row.get('id'),'flow':row.get('flow')})
    if p.get('layout'):
        if not isinstance(p['layout'],list):raise ValueError('Некорректная схема экранов')
        for row in p['layout']:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not 1<=len(row['id'])<=512:raise ValueError('Некорректный монитор')
        if not displays:info['displays']=[{'id':r['id'],'current':'1x1@60'} for r in p['layout']]
        # Geometry depends on the current physical modes: check structure here, live adjacency at apply.
        check=virtual.pop('layout')
        if len(check)>16 or len({r['id'] for r in check})!=len(check) or sum(r.get('primary') is True for r in check)!=1:raise ValueError('Некорректная схема экранов')
        for r in check:
            if set(r)!={'id','x','y','primary'} or type(r['primary'])!=bool or any(type(r[k])!=int or not -32768<=r[k]<=32767 for k in ('x','y')):raise ValueError('Некорректное положение экрана')
    validate_plan(virtual,info,[{'id':u} for u in p.get('updates',[])],demo=True)
    return p

class Workspace:
    def __init__(self,directory):
        self.path=Path(directory)/'workspace.json';self.warning=None
        self.value={'draft':{},'favorites':[],'theme':'light','mode':'basic','profiles':[],'recent':[],'ui':{}}
        self.lock=threading.RLock()
        if self.path.exists():
            try:
                if self.path.stat().st_size>262144:raise ValueError('Файл настроек слишком большой')
                self.value=self.validate(json.loads(self.path.read_text(encoding='utf-8')))
            except Exception:
                self.warning='Сохранённые параметры повреждены. Система не изменена; начат новый выбор.'
        self.disk_signature=self._disk_signature()
    def _disk_signature(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
    def validate(self,body):
        if not isinstance(body,dict) or set(body)-{'draft','favorites','theme','mode','profiles','recent','ui'}:raise ValueError('Неизвестные параметры приложения')
        draft=saved_plan(body.get('draft',{}))
        theme=body.get('theme','light');mode=body.get('mode','basic')
        if theme not in ('dark','light','system') or mode not in ('basic','all'):raise ValueError('Неизвестный режим интерфейса')
        lists={}
        for key,limit in [('favorites',150),('recent',8)]:
            entries=body.get(key,[])
            if not isinstance(entries,list) or len(entries)>limit or any(not isinstance(i,str) or i not in FAVORITES for i in entries):raise ValueError('Неизвестный пункт '+key)
            lists[key]=list(dict.fromkeys(entries))
        profiles=body.get('profiles',[])
        if not isinstance(profiles,list) or len(profiles)>20:raise ValueError('Можно сохранить до 20 профилей')
        seen=set()
        for profile in profiles:
            if not isinstance(profile,dict) or set(profile)!={'name','plan'} or not isinstance(profile['name'],str) or not 1<=len(profile['name'].strip())<=60:raise ValueError('Некорректный профиль')
            name=profile['name'].strip()
            if name.casefold() in seen:raise ValueError('Названия профилей должны различаться')
            seen.add(name.casefold());saved_plan(profile['plan'])
        value={'draft':draft,'theme':theme,'mode':mode,'profiles':copy.deepcopy(profiles),'ui':ui_preferences(body.get('ui',{})),**lists}
        if len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>262144:raise ValueError('Слишком много сохранённых данных')
        return value
    def save(self,body):
        with self.lock:
            if self._disk_signature()!=self.disk_signature:raise ValueError('Выбор изменён в другом окне. Обновите приложение, чтобы не перезаписать его.')
            value=self.validate(body);atomic_json(self.path,value);self.value=value;self.disk_signature=self._disk_signature()
            return copy.deepcopy(value)
    def clear_successes(self,items):
        draft=copy.deepcopy(self.value['draft'])
        for op in items:
            if op.get('status')!='success':continue
            kind,key=op.get('kind'),op.get('key')
            if kind=='setting' and draft.get('settings',{}).get(key)==op.get('value'):draft['settings'].pop(key,None)
            if kind=='package_manager':draft.pop('prepare_apps',None)
            if kind=='languages' and draft.get('languages')==op.get('value'):draft['languages']=[]
            if kind=='layout' and draft.get('layout')==op.get('value'):draft['layout']=[]
            if kind=='startup':draft['startup']=[v for v in draft.get('startup',[]) if v['id']!=key or v['enabled']!=op.get('value')]
            if kind=='upgrade':draft['upgrades']=[v for v in draft.get('upgrades',[]) if v!=key]
            if kind in ['app','update']:
                field='apps' if kind=='app' else 'updates';draft[field]=[v for v in draft.get(field,[]) if v!=key]
            if kind=='audio_default':
                draft['audio_defaults']=[r for r in draft.get('audio_defaults',[]) if r!=op.get('value')]
            if kind in ['display','brightness','audio']:
                field={'display':'displays','brightness':'brightness','audio':'audio'}[kind]
                def matches(v):
                    if v['id']!=key:return False
                    if kind=='audio':return v==op.get('value')
                    if kind=='brightness':return v.get('value')==op.get('value')
                    return v.get('mode')==op.get('value') and v.get('orientation')==op.get('orientation')
                draft[field]=[v for v in draft.get(field,[]) if not matches(v)]
            if kind=='restore_point':draft['restore_point']=False
        self.save({**self.value,'draft':draft})
