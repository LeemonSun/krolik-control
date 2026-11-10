"""Prepare official WinGet downloads without launching cached installers."""
import os
from pathlib import Path
import secrets,shutil,time
from .files import check,inside,hash_file
from .workspace import atomic_json

def download(backend,root,apps,stop,stage):
 check(stop);root=Path(root)
 from .storage import linked
 if not root.is_dir() or linked(root):raise ValueError('Выберите обычную папку назначения')
 from .files import rename_root
 root=rename_root(root.resolve())
 if shutil.disk_usage(root).free<1024**3:raise ValueError('Для подготовки нужно не менее 1 ГиБ свободного места')
 backend.prepare_package_manager();dest=root/('KrolikOffline-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4));dest.mkdir();manifest={'version':1,'complete':False,'created':time.time(),'apps':[],'source':'winget','architecture':'x64','files':[]};path=dest/'KrolikControl-cache.json';atomic_json(path,manifest)
 try:
  for ident in apps:
   check(stop)
   if shutil.disk_usage(dest).free<1024**3:raise ValueError('Свободного места осталось меньше 1 ГиБ; завершённые загрузки сохранены')
   folder=dest/ident;folder.mkdir();stage('Загрузка '+ident)
   backend.package_manager._command(['download','--id',ident,'--exact','--source','winget','--architecture','x64','--download-directory',str(folder),'--accept-source-agreements','--accept-package-agreements','--disable-interactivity'],timeout=900)
   files=[]
   for base,dirs,names in os.walk(folder,followlinks=False):
    for name in dirs+names:
     if linked(Path(base)/name):raise ValueError('В наборе появилась ссылка')
    for name in names:
     check(stop);p=Path(base)/name;inside(dest,p)
     sha=hash_file(p,stop,stage,dest);files.append({'path':p.relative_to(dest).as_posix(),'bytes':p.stat().st_size,'sha256':sha})
     if len(files)>10000:raise ValueError('Слишком много файлов в загрузке')
   if not files:raise ValueError('WinGet не сохранил файлы выбранной программы')
   manifest['files']+=files;manifest['apps'].append(ident);atomic_json(path,manifest)
  manifest['complete']=True;atomic_json(path,manifest)
  return {'title':'Установщики подготовлены','path':str(dest),'items':[{'name':a} for a in manifest['apps']],'files':len(manifest['files']),'note':'Файлы загружены через WinGet с его проверкой хешей; дополнительно сохранён список SHA-256. Некоторые веб-установщики всё равно требуют интернет. Этот шаг не запускает установщики и не обещает полностью автономную установку.'}
 except BaseException as e:
  manifest['error']=str(e)[:1000];atomic_json(path,manifest);raise
