"""Explicit maintenance operations; no arbitrary commands or package IDs."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from .catalog import APPS
from .workspace import atomic_json

RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'

def program_inventory(backend):
    from .installed_apps import local_inventory
    from .packages import ProcessError
    result=local_inventory()
    manager=backend.package_manager
    if not manager.resolve():
        for row in result:row['update_check']='requires_setup'
        return result
    fd,name=tempfile.mkstemp(suffix='.json');os.close(fd)
    try:
        manager._command(['export','--output',name,'--source','winget','--include-versions','--accept-source-agreements','--disable-interactivity'],timeout=180)
        raw=json.loads(Path(name).read_text(encoding='utf-8-sig'))
        installed={}
        for source in raw.get('Sources',[]):
            for package in source.get('Packages',[]):
                if package.get('PackageIdentifier') in APPS:installed.setdefault(package['PackageIdentifier'],set()).add(str(package.get('Version','')))
        for row in result:
            if row['id'] in installed:
                row['installed']=True;row['managed_versions']=sorted(installed[row['id']])
                if not row.get('version'):row['version']=' / '.join(row['managed_versions'])
    except Exception:
        for row in result:row['update_check']='unavailable'
        # A failed read is never evidence that the applications disappeared.
        return result
    finally:Path(name).unlink(missing_ok=True)
    try:
        try:text=manager._command(['upgrade','--source','winget','--accept-source-agreements','--disable-interactivity'],timeout=180)
        except ProcessError as exc:
            if exc.code!=0x8a15002b:raise
            text=''
        for row in result:
            row['update_check']='checked'
            for line in text.splitlines():
                match=re.search(r'(?<!\S)'+re.escape(row['id'])+r'\s+(\S+)\s+(\S+)(?:\s|$)',line,re.I)
                if match and row['installed']:
                    row['update_available']=True;row['available_version']=match.group(2);break
    except Exception:
        for row in result:row['update_check']='unavailable'
    return result

def startup_id(kind,name,value=''):
    return hashlib.sha256((kind+'\0'+name+'\0'+str(value)).encode()).hexdigest()

def startup_directory():
    return Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'

def _disabled(backend):
    path=Path(backend.directory)/'disabled-startup.json'
    if not path.exists():return []
    if path.stat().st_size>1048576:raise ValueError('Список отключённых программ повреждён')
    rows=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('Список отключённых программ повреждён')
    for row in rows:
        if not isinstance(row,dict) or row.get('kind') not in ('registry','folder') or not isinstance(row.get('name'),str) or not 1<=len(row['name'])<=260:raise ValueError('Повреждена запись автозагрузки')
        if row['kind']=='registry':
            if not isinstance(row.get('command'),str) or len(row['command'])>32768 or row.get('type') not in (1,2):raise ValueError('Повреждена запись автозагрузки')
            value=row['command']
        else:
            if Path(row['name']).name!=row['name'] or any(c in row['name'] for c in '/\\:') or row['name'] in ('.','..'):raise ValueError('Недопустимый файл автозагрузки')
            value=''
        if row.get('id')!=startup_id(row['kind'],row['name'],value):raise ValueError('ID автозагрузки не совпадает')
    return rows

def startup_inventory(backend):
    import winreg as R
    result=[]
    for hive,scope in [(R.HKEY_CURRENT_USER,'Пользователь'),(R.HKEY_LOCAL_MACHINE,'Все пользователи')]:
        try:
            with R.OpenKey(hive,RUN_KEY) as key:
                i=0
                while True:
                    try:name,value,kind=R.EnumValue(key,i)
                    except OSError:break
                    i+=1
                    if kind not in (R.REG_SZ,R.REG_EXPAND_SZ):continue
                    ident=startup_id('registry',name,value) if scope=='Пользователь' else startup_id('machine',name,value)
                    result.append({'id':ident,'kind':'registry' if scope=='Пользователь' else 'machine','name':name,'command':value,'type':kind,'enabled':True,'controllable':scope=='Пользователь','source':scope+' · реестр'})
        except FileNotFoundError:pass
    folder=startup_directory();folder.mkdir(parents=True,exist_ok=True)
    for file in folder.iterdir():
        if file.is_file() and file.name.lower()!='desktop.ini':result.append({'id':startup_id('folder',file.name),'kind':'folder','name':file.name,'enabled':True,'controllable':True,'source':'Пользователь · папка автозагрузки'})
    active={r['id'] for r in result}
    for row in _disabled(backend):
        if row['id'] not in active:result.append({**row,'enabled':False,'controllable':True,'source':'Отключено в Krolik Control'})
    # StartupApproved is read only: do not claim a Run entry will launch if Windows blocked it.
    for row in result:
        if row['kind'] not in ('registry','folder'):continue
        try:
            key_name=r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved' + chr(92) + ('Run' if row['kind']=='registry' else 'StartupFolder')
            with R.OpenKey(R.HKEY_CURRENT_USER,key_name) as key:approval,_=R.QueryValueEx(key,row['name'])
            if not isinstance(approval,bytes) or not approval or approval[0] not in (2,6):
                row['controllable']=False;row['state_hint']='Отключено или ограничено Windows; доступен просмотр'
                if isinstance(approval,bytes) and approval and approval[0] in (3,7):row['enabled']=False
        except FileNotFoundError:pass
    return sorted(result,key=lambda r:(not r['controllable'],r['name'].casefold()))

def set_startup(backend,ident,enabled):
    import winreg as R
    rows=startup_inventory(backend);row=next((r for r in rows if r['id']==ident and r['controllable']),None)
    if row is None:raise ValueError('Запись автозагрузки изменилась; обновите список')
    if row['enabled']==enabled:return
    disabled=_disabled(backend);path=Path(backend.directory)/'disabled-startup.json'
    folder=startup_directory();stash=Path(backend.directory)/'disabled-startup-files';stash.mkdir(exist_ok=True)
    if not enabled:
        stored={k:row[k] for k in ('id','kind','name')}
        if row['kind']=='registry':stored.update(command=row['command'],type=row['type'])
        disabled=[r for r in disabled if r['id']!=ident]+[stored];atomic_json(path,disabled)
        if row['kind']=='registry':
            with R.OpenKey(R.HKEY_CURRENT_USER,RUN_KEY,0,R.KEY_READ|R.KEY_SET_VALUE) as key:
                value,kind=R.QueryValueEx(key,row['name'])
                if startup_id('registry',row['name'],value)!=ident:raise ValueError('Программа изменила автозапуск; повторите проверку')
                R.DeleteValue(key,row['name'])
        else:
            source=folder/row['name'];target=stash/row['name']
            if target.exists():raise ValueError('Резервный файл автозапуска уже существует')
            source.rename(target)
    else:
        if row['kind']=='registry':
            with R.CreateKeyEx(R.HKEY_CURRENT_USER,RUN_KEY,0,R.KEY_READ|R.KEY_SET_VALUE) as key:
                try:R.QueryValueEx(key,row['name'])
                except FileNotFoundError:R.SetValueEx(key,row['name'],0,row['type'],row['command'])
                else:raise ValueError('С этим именем уже есть запись; она не будет перезаписана')
        else:
            target=folder/row['name']
            if target.exists():raise ValueError('Файл с этим именем уже существует')
            (stash/row['name']).rename(target)
        atomic_json(path,[r for r in disabled if r['id']!=ident])
