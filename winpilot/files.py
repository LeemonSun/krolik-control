"""Selected-folder analysis and file tools. No deletion, no following reparse points."""
from collections import defaultdict
import hashlib
import os
from pathlib import Path
import secrets
import stat
import time
from .storage import linked
from .workspace import atomic_json

class Stopped(Exception):pass
def check(stop):
    if stop.is_set():raise Stopped('Проверка остановлена')
def ident(p):
    s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or linked(p):raise ValueError('Файл недоступен или является ссылкой')
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]
def inside(root,p):
    if linked(root) or root.resolve()!=root or root not in p.resolve().parents:raise ValueError('Выбранная папка изменилась')
    parent=p.parent
    while parent!=root:
        if linked(parent):raise ValueError('В пути появилась ссылка')
        parent=parent.parent

def walk(root,stop,stage,*,max_files=250000,seconds=60,deduplicate_hardlinks=True):
    root=Path(root)
    if not root.is_dir() or linked(root):raise ValueError('Выберите обычную папку')
    root=root.resolve();started=time.monotonic();seen=set();files=[];skipped=0;limited=False;pending=[root];last=0;entries=0
    while pending:
        check(stop)
        if len(files)>=max_files or time.monotonic()-started>seconds:limited=True;break
        folder=pending.pop()
        try:
            if folder!=root:inside(root,folder)
            if linked(folder):skipped+=1;continue
            with os.scandir(folder) as rows:
                for e in rows:
                    check(stop);p=Path(e.path);entries+=1
                    if entries>max_files*2:limited=True;break
                    if time.monotonic()-started>seconds or len(files)>=max_files:limited=True;break
                    try:
                        s=e.stat(follow_symlinks=False)
                        if e.is_symlink() or getattr(s,'st_file_attributes',0)&0x400:skipped+=1;continue
                        if stat.S_ISDIR(s.st_mode):pending.append(p);continue
                        if not stat.S_ISREG(s.st_mode):continue
                        # On Windows DirEntry.stat() may report zero device/inode.
                        # Read the actual identity before comparing later or deduplicating hard links.
                        if not s.st_ino:
                            s=p.lstat()
                            if not stat.S_ISREG(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:
                                skipped+=1;continue
                        relative=str(p.relative_to(root))
                        if len(relative.encode('utf-8'))>2000:skipped+=1;limited=True;continue
                        key=(s.st_dev,s.st_ino) if s.st_ino else str(p)
                        if deduplicate_hardlinks and key in seen:continue
                        seen.add(key);files.append({'path':relative,'bytes':s.st_size,'identity':[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns]})
                    except (OSError,ValueError):skipped+=1
        except (OSError,ValueError):skipped+=1
        if time.monotonic()-last>.25:stage('Просмотрено файлов: '+str(len(files)));last=time.monotonic()
        if limited:break
    return files,{'limited':limited,'skipped':skipped,'seconds':round(time.monotonic()-started,2),'root':str(root)}

def analyze(root,stop,stage):
    rows,meta=walk(root,stop,stage);folders=defaultdict(int);types=defaultdict(lambda:[0,0]);total=0
    for r in rows:
        p=Path(r['path']);parts=p.parts;folders[parts[0] if len(parts)>1 else 'Файлы в корне']+=r['bytes'];ext=p.suffix.casefold() or 'Без расширения';types[ext][0]+=r['bytes'];types[ext][1]+=1;total+=r['bytes']
    return {'kind':'disk_map','title':'Место в выбранной папке','files':len(rows),'bytes':total,'folders':[{'name':k,'bytes':v} for k,v in sorted(folders.items(),key=lambda x:x[1],reverse=True)[:80]],'largest':[{'path':r['path'],'bytes':r['bytes']} for r in sorted(rows,key=lambda x:x['bytes'],reverse=True)[:50]],'types':[{'name':k,'bytes':v[0],'files':v[1]} for k,v in sorted(types.items(),key=lambda x:x[1][0],reverse=True)[:30]],**meta,'note':'Логический размер доступных файлов. Жёсткие ссылки учитываются один раз; облачные и другие reparse-файлы пропускаются. Это не весь занятый объём тома.'}

def hash_file(p,stop,stage,root=None):
    p=Path(p);before=ident(p);h=hashlib.sha256();n=0;last=0
    if root:inside(Path(root),p)
    with p.open('rb') as f:
        opened=os.fstat(f.fileno())
        if [opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns]!=before:raise ValueError('Файл изменился перед чтением')
        while True:
            check(stop);b=f.read(1024*1024)
            if not b:break
            h.update(b);n+=len(b)
            if time.monotonic()-last>.25:stage('Проверено: '+str(n//1024**2)+' МиБ');last=time.monotonic()
    if ident(p)!=before:raise ValueError('Файл изменился во время чтения; результат не сохранён')
    return h.hexdigest()

def duplicates(root,stop,stage):
    root=Path(root).resolve();rows,meta=walk(root,stop,stage,max_files=20000,seconds=30);sizes=defaultdict(list);groups=[];used=0;started=time.monotonic()
    for r in rows:
        if 0<r['bytes']<=2*1024**3:sizes[r['bytes']].append(r)
    for size,candidates in sizes.items():
        if len(candidates)<2:continue
        by_hash=defaultdict(list)
        for r in candidates:
            check(stop)
            if used+r['bytes']>16*1024**3 or time.monotonic()-started>120:meta['limited']=True;break
            p=root/r['path']
            try:
                inside(root,p)
                if ident(p)!=r['identity']:raise ValueError('Файл изменился')
                sha=hash_file(p,stop,stage,root);by_hash[sha].append(r['path']);used+=r['bytes']
            except (OSError,ValueError):meta['skipped']+=1
        for sha,paths in by_hash.items():
            if len(paths)>1:groups.append({'sha256':sha,'bytes_each':size,'paths':paths[:10],'copies':len(paths)})
        if meta['limited'] and (used>=16*1024**3 or time.monotonic()-started>120):break
    return {'kind':'duplicates','title':'Совпадающие файлы','groups':sorted(groups,key=lambda r:r['bytes_each']*(r['copies']-1),reverse=True)[:20],'groups_total':len(groups),'hashed_bytes':used,**meta,'note':'Совпадение размера и SHA-256. Файлы не удалялись. Жёсткие ссылки исключены; результаты относятся к просмотренной части папки.'}

def valid_name(name):
    if not isinstance(name,str) or not 1<=len(name)<=200 or name[-1:] in (' ','.') or any(c in name for c in '<>:"/\\|?*') or any(ord(c)<32 for c in name):return False
    try:
        if len(name.encode('utf-16-le'))//2>200:return False
    except UnicodeError:return False
    return name.split('.')[0].rstrip(' ').casefold() not in {'con','conin$','conout$','prn','aux','nul',*[f'com{i}' for i in '123456789¹²³'],*[f'lpt{i}' for i in '123456789¹²³']} and name not in ('.','..')

def protected_locations():
    import sys
    result=[Path(__file__).resolve().parents[1],Path(sys.executable).resolve().parent]
    if os.name=='nt':
        result += [Path(os.environ[k]) for k in ('SystemRoot','windir','ProgramFiles','ProgramFiles(x86)','ProgramW6432','ProgramData','LOCALAPPDATA','APPDATA') if os.environ.get(k)]
        import ctypes as C
        b=C.create_unicode_buffer(32768);k=C.WinDLL('kernel32');k.GetWindowsDirectoryW.argtypes=[C.c_wchar_p,C.c_uint32]
        if k.GetWindowsDirectoryW(b,len(b)):result.append(Path(b.value))
        import winreg as R
        try:
            with R.OpenKey(R.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion',0,R.KEY_READ|R.KEY_WOW64_64KEY) as key:
                for name in ('ProgramFilesDir','ProgramFilesDir (x86)'):
                    try:result.append(Path(R.QueryValueEx(key,name)[0]))
                    except OSError:pass
        except OSError:pass
    return result

def rename_root(root,protected=None):
    root=Path(root)
    if root==Path(root.anchor):raise ValueError('Для переименования выберите отдельную папку с файлами')
    if protected is None:protected=protected_locations()
    if any(root==Path(p).resolve() or Path(p).resolve() in root.parents for p in protected):raise ValueError('Эта папка защищена. Выберите папку с личными файлами.')
    return root

def rename_preview(root,find,replace):
    if not isinstance(find,str) or not find or len(find)>100 or not isinstance(replace,str) or len(replace)>100:raise ValueError('Введите искомый текст и замену до 100 символов')
    root=rename_root(Path(root).resolve());rows=[];existing=set();outputs=set();candidates=[];started=time.monotonic()
    with os.scandir(root) as entries:
        for i,e in enumerate(entries):
            if i>=20000 or time.monotonic()-started>5:raise ValueError('Папка слишком большая для переименования одним списком; выберите вложенную папку')
            existing.add(e.name.casefold())
            if find not in e.name or e.is_symlink() or not e.is_file(follow_symlinks=False):continue
            candidates.append(Path(e.path))
            if len(candidates)>500:raise ValueError('За один раз можно переименовать не более 500 файлов')
    for p in sorted(candidates):
        if linked(p):continue
        new=p.name.replace(find,replace)
        if new==p.name:continue
        if not valid_name(new) or new.casefold() in outputs:raise ValueError('Недопустимое или повторяющееся новое имя: '+new)
        rows.append({'before':p.name,'after':new,'identity':ident(p)});outputs.add(new.casefold())
    old={r['before'].casefold() for r in rows}
    if any(r['after'].casefold() in existing-old for r in rows):raise ValueError('Одно из новых имён уже занято')
    if not rows:raise ValueError('Подходящих файлов нет')
    return {'root':str(root),'rows':rows}

def move_noreplace(source,dest):
    if os.name=='nt':
        import ctypes as C
        k=C.WinDLL('kernel32',use_last_error=True);k.MoveFileExW.argtypes=[C.c_wchar_p,C.c_wchar_p,C.c_uint32]
        if not k.MoveFileExW(str(source),str(dest),0):raise OSError(C.get_last_error(),'Не удалось переименовать файл')
    else:
        os.link(source,dest,follow_symlinks=False)
        try:source.unlink()
        except BaseException:dest.unlink();raise

def rename_apply(job,journal):
    root=rename_root(Path(job['root']));rows=job['rows'];state={'version':1,'root':str(root),'rows':rows,'state':'prepared','moved':0,'committed':0}
    if not root.is_dir() or linked(root) or root.resolve()!=root:raise ValueError('Папка недоступна')
    for r in rows:
        if not valid_name(r['before']) or not valid_name(r['after']):raise ValueError('Недопустимое имя')
        p=root/r['before'];inside(root,p)
        if ident(p)!=r['identity']:raise ValueError('Файл изменился после просмотра: '+r['before'])
        r['temporary']='.krolik-'+secrets.token_hex(16)+'.tmp'
    atomic_json(journal,state)
    try:
        for i,r in enumerate(rows):
            inside(root,root/r['before'])
            if ident(root/r['before'])!=r['identity']:raise ValueError('Файл изменился')
            move_noreplace(root/r['before'],root/r['temporary']);state['moved']=i+1;atomic_json(journal,state)
        for i,r in enumerate(rows):
            inside(root,root/r['temporary'])
            if ident(root/r['temporary'])!=r['identity']:raise ValueError('Файл изменился')
            move_noreplace(root/r['temporary'],root/r['after']);state['committed']=i+1;atomic_json(journal,state)
        state['state']='confirmed';atomic_json(journal,state)
    except BaseException:
        # Roll completed destinations back to their private temporary names first (cycles).
        for r in rows[:state['committed']]:
            try:
                if ident(root/r['after'])==r['identity']:move_noreplace(root/r['after'],root/r['temporary'])
            except (OSError,ValueError):pass
        for r in rows[:state['moved']]:
            try:
                if ident(root/r['temporary'])==r['identity']:move_noreplace(root/r['temporary'],root/r['before'])
            except (OSError,ValueError):pass
        state['state']='error';atomic_json(journal,state);raise
    return {'kind':'rename','title':'Файлы переименованы','count':len(rows),'rows':[{'before':r['before'],'after':r['after']} for r in rows],'can_undo':True,'note':'Возврат доступен, пока имена и файлы не изменились.'}

def recovery_plan(journal):
    """Infer the surviving location of every file; journal counters alone are insufficient."""
    import json,re
    p=Path(journal)
    if p.stat().st_size>512000:raise ValueError('Журнал переименования слишком большой')
    saved=json.loads(p.read_text(encoding='utf-8'));root=Path(saved['root']);rows=saved.get('rows')
    if saved.get('state') not in ('prepared','error') or not isinstance(rows,list) or not 1<=len(rows)<=500:raise ValueError('Нет незавершённого переименования')
    if not root.is_dir() or linked(root) or root.resolve()!=root:raise ValueError('Исходная папка недоступна')
    result=[];seen=set();entries={}
    for i,p in enumerate(root.iterdir()):
        if i>=100000:raise ValueError('Слишком много объектов в папке для восстановления')
        entries[p.name.casefold() if os.name=='nt' else p.name]=p.name
    for row in rows:
        before=row.get('before');after=row.get('after');temporary=row.get('temporary');identity=row.get('identity')
        if not valid_name(before) or not valid_name(after) or not isinstance(temporary,str) or not re.fullmatch(r'\.krolik-[a-f0-9]{32}\.tmp',temporary) or not isinstance(identity,list) or len(identity)!=4 or any(type(v)!=int or v<0 for v in identity):raise ValueError('Повреждён журнал имён')
        if before.casefold() in seen:raise ValueError('Повтор имени в журнале')
        seen.add(before.casefold());found=[]
        actual_names={entries.get(name.casefold() if os.name=='nt' else name,name) for name in (before,temporary,after)}
        for name in actual_names:
            target=root/name;inside(root,target)
            try:
                if ident(target)==identity:found.append(name)
            except FileNotFoundError:pass
        if len(found)!=1:raise ValueError('Файл изменился, пропал или его расположение неоднозначно: '+before)
        if found[0]!=before:result.append({'before':found[0],'after':before,'identity':identity})
    return {'root':str(root),'rows':result}
