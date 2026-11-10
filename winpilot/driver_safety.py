"""Export existing third-party packages before a confirmed driver-update batch."""
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import time
from .workspace import atomic_json

def create(backend,*,automatic=True):
    if hasattr(backend,'is_admin') and not backend.is_admin():
        from .privilege import request
        return request(backend,'driver_backup',{})
    from .care_windows import driver_root
    root=driver_root();root.mkdir(parents=True,exist_ok=True)
    if root.is_symlink() or getattr(os.path,'isjunction',lambda p:False)(root):raise ValueError('Папка копий драйверов не должна быть ссылкой')
    if shutil.disk_usage(root).free<512*1024**2:raise ValueError('Для копии драйверов нужно не менее 512 МиБ свободного места. Обновление не началось.')
    dest=root/('Drivers-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4));dest.mkdir()
    try:
        backend.run([str(Path(os.environ['SystemRoot'])/'System32/pnputil.exe'),'/export-driver','*',str(dest)],timeout=600)
        files=[]
        for base,dirs,names in os.walk(dest,followlinks=False):
            for name in dirs+names:
                f=Path(base)/name
                if f.is_symlink() or getattr(os.path,'isjunction',lambda p:False)(f):raise ValueError('В копии обнаружена ссылка')
            for name in names:
                f=Path(base)/name;h=hashlib.sha256()
                with f.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
                files.append({'path':f.relative_to(dest).as_posix(),'bytes':f.stat().st_size,'sha256':h.hexdigest()})
                if len(files)>100000:raise ValueError('Слишком много файлов в копии')
        manifest={'version':1,'created':time.time(),'complete':True,'automatic':automatic,'packages':sum(f['path'].lower().endswith('.inf') for f in files),'files':files}
        atomic_json(dest/'KrolikControl-backup.json',manifest)
        return {'path':str(dest),'packages':manifest['packages'],'message':'Копия сторонних пакетов: '+str(manifest['packages'])+'. '+str(dest)+'. Встроенные драйверы Windows и фирменные программы сюда не входят.'}
    except BaseException:
        shutil.rmtree(dest,ignore_errors=True);raise

def verify_manifest(dest):
    """Check our hashed copies; legacy manual copies remain signature-checked by Windows."""
    import json
    p=Path(dest);f=p/'KrolikControl-backup.json'
    if f.stat().st_size>32*1024**2:raise ValueError('Слишком большой список файлов копии')
    m=json.loads(f.read_text(encoding='utf-8'))
    if not isinstance(m,dict) or m.get('complete') is not True:raise ValueError('Копия не завершена')
    if 'files' not in m:return
    if not isinstance(m['files'],list) or len(m['files'])>100000:raise ValueError('Повреждён список копии')
    expected_paths=[row.get('path') for row in m['files'] if isinstance(row,dict)]
    if len(expected_paths)!=len(m['files']) or any(not isinstance(n,str) for n in expected_paths) or len(set(expected_paths))!=len(expected_paths):raise ValueError('Повтор или повреждение списка копии')
    actual=set()
    for base,dirs,files in os.walk(p,followlinks=False):
        for name in dirs+files:
            target=Path(base)/name
            if target.is_symlink() or getattr(os.path,'isjunction',lambda p:False)(target):raise ValueError('Копия содержит ссылку')
        actual.update((Path(base)/name).relative_to(p).as_posix() for name in files if Path(base)/name!=f)
    if actual!=set(expected_paths):raise ValueError('Состав копии изменился')
    for row in m['files']:
        if not isinstance(row,dict) or not isinstance(row.get('path'),str):raise ValueError('Повреждён путь копии')
        name=row['path'];target=(p/name).resolve()
        if not name or '\\' in name or ':' in name or target==p.resolve() or p.resolve() not in target.parents:raise ValueError('Недопустимый путь копии')
        if target.is_symlink() or not target.is_file() or target.stat().st_size!=row.get('bytes'):raise ValueError('Состав копии изменился')
        h=hashlib.sha256()
        with target.open('rb') as stream:
            for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
        if h.hexdigest()!=row.get('sha256'):raise ValueError('Содержимое копии изменилось. Восстановление остановлено.')
