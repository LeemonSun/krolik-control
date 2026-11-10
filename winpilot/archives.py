"""Bounded ZIP operations: preview, no overwrite, staged publication."""
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import struct
import tempfile
import threading
import time
import zipfile
from .files import ident, walk, check, valid_name
from .storage import linked

MAX_ENTRIES=10000
MAX_TOTAL=2*1024**3
MAX_FILE=512*1024**2

class CompressionRatioError(ValueError):pass

def preflight(path):
    # Bound the central directory BEFORE ZipFile allocates a ZipInfo per entry.
    with Path(path).open('rb') as stream:
        stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-65557));tail=stream.read()
    position=len(tail)
    while True:
        position=tail.rfind(b'PK\x05\x06',0,position)
        if position<0:raise ValueError('Оглавление ZIP не найдено')
        if position+22<=len(tail):
            fields=struct.unpack_from('<4s4H2LH',tail,position)
            if position+22+fields[-1]==len(tail):break
    if fields[1] or fields[2] or fields[3]!=fields[4]:raise ValueError('Многотомный ZIP не поддерживается')
    if fields[4]>MAX_ENTRIES or fields[5]>16*1024**2:raise ValueError('Оглавление ZIP превышает ограничения')
    end=size-len(tail)+position
    if fields[6]+fields[5]!=end:raise ValueError('Неподдерживаемая структура ZIP')
    with Path(path).open('rb') as stream:
        stream.seek(fields[6]);count=0
        while stream.tell()<end:
            header=stream.read(46)
            if len(header)!=46 or header[:4]!=b'PK\x01\x02':raise ValueError('Повреждено оглавление ZIP')
            count+=1
            if count>MAX_ENTRIES:raise ValueError('Слишком много объектов в архиве')
            lengths=struct.unpack_from('<3H',header,28);stream.seek(sum(lengths),1)
            if stream.tell()>end:raise ValueError('Повреждено оглавление ZIP')
        if count!=fields[4]:raise ValueError('Число объектов ZIP не совпало с оглавлением')

def members(archive):
    entries=archive.infolist()
    if len(entries)>MAX_ENTRIES:raise ValueError('Слишком много объектов в архиве')
    seen={};total=0
    for entry in entries:
        name=entry.filename
        path=PurePosixPath(name)
        if ('\\' in entry.orig_filename or '\x00' in entry.orig_filename or path.is_absolute() or not path.parts
                or any(p in ('.','..') or not valid_name(p) for p in path.parts)):
            raise ValueError('Недопустимый путь в архиве: '+name[:120])
        mode=entry.external_attr>>16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)):
            raise ValueError('Ссылки и специальные файлы в ZIP не поддерживаются')
        if entry.flag_bits&1:raise ValueError('Зашифрованный ZIP пока не поддерживается')
        if entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError('Неподдерживаемое сжатие ZIP')
        key='/'.join(path.parts).casefold()
        if key in seen:raise ValueError('Повторяющийся путь в архиве')
        seen[key]=entry.is_dir()
        if entry.file_size>MAX_FILE or entry.file_size<0:raise ValueError('Файл в архиве превышает 512 МиБ')
        total+=entry.file_size
        if total>MAX_TOTAL:raise ValueError('Распакованный архив превышает 2 ГиБ')
        if entry.file_size>1024**2 and entry.file_size>max(1,entry.compress_size)*1000:raise CompressionRatioError('Слишком высокая степень сжатия ZIP')
    for key in seen:
        parts=key.split('/')
        if any(seen.get('/'.join(parts[:i])) is False for i in range(1,len(parts))):raise ValueError('Конфликт файла и папки в ZIP')
    return entries,total

def inspect(path):
    before=ident(path)
    preflight(path)
    with zipfile.ZipFile(path) as archive:
        entries,total=members(archive)
        result={'entries':len(entries),'bytes':total,'items':[{'name':e.filename,'size':e.file_size} for e in entries[:200]],'truncated':len(entries)>200}
    if ident(path)!=before:raise ValueError('Архив изменился во время чтения')
    return result

def publish(stage,destination):
    if destination.exists() or destination.is_symlink():raise ValueError('Папка или файл результата уже существует')
    # Windows rename never overwrites a destination; the application targets Windows.
    os.rename(stage,destination)

def extract(path,stop):
    path=Path(path);before=ident(path)
    preflight(path)
    destination=path.with_name(path.stem+'-unpacked')
    if destination.exists():raise ValueError('Папка результата уже существует')
    stage=Path(tempfile.mkdtemp(prefix='.krolik-unzip-',dir=path.parent))
    try:
        with zipfile.ZipFile(path) as archive:
            entries,total=members(archive);written=0
            for entry in entries:
                check(stop);target=stage.joinpath(*PurePosixPath(entry.filename).parts)
                if entry.is_dir():target.mkdir(parents=True,exist_ok=True);continue
                target.parent.mkdir(parents=True,exist_ok=True)
                count=0
                with archive.open(entry) as source,target.open('xb') as output:
                    while True:
                        check(stop);chunk=source.read(1024**2)
                        if not chunk:break
                        count+=len(chunk);written+=len(chunk)
                        if count>entry.file_size or written>MAX_TOTAL:raise ValueError('Размер распаковки не совпал с оглавлением')
                        output.write(chunk)
                if count!=entry.file_size:raise ValueError('Архив повреждён')
        if ident(path)!=before:raise ValueError('Архив изменился во время распаковки')
        check(stop);publish(stage,destination)
        return {'destination':str(destination),'entries':len(entries),'bytes':written}
    finally:
        if stage.exists() and not linked(stage) and stage.parent.resolve()==path.parent.resolve():shutil.rmtree(stage)

def create(folder,stop):
    folder=Path(folder)
    if linked(folder) or folder.resolve()!=folder:raise ValueError('Выбранная папка является ссылкой')
    destination=folder.with_name(folder.name+'.zip')
    if destination.exists():raise ValueError('ZIP с таким именем уже существует')
    rows,meta=walk(folder,stop,lambda _:None,max_files=MAX_ENTRIES,seconds=60,deduplicate_hardlinks=False)
    if meta['limited'] or meta['skipped']:raise ValueError('Часть папки недоступна или содержит ссылки; ZIP не создан')
    if sum(r['bytes'] for r in rows)>MAX_TOTAL:raise ValueError('Папка превышает 2 ГиБ')
    fd,name=tempfile.mkstemp(prefix='.krolik-zip-',suffix='.tmp',dir=folder.parent);os.close(fd);stage=Path(name)
    def write_archive(compression):
        with zipfile.ZipFile(stage,'w',compression,compresslevel=6 if compression==zipfile.ZIP_DEFLATED else None) as archive:
            directories=0;started=time.monotonic()
            for parent,names,_ in os.walk(folder,followlinks=False):
                for name in names:
                    check(stop);directory=Path(parent)/name;directories+=1
                    if directories+len(rows)>MAX_ENTRIES or time.monotonic()-started>60:raise ValueError('Слишком много папок для ZIP')
                    if linked(directory):raise ValueError('Папка содержит ссылку')
                    archive.writestr(directory.relative_to(folder).as_posix()+'/',b'')
            for row in rows:
                check(stop);path=folder/row['path']
                if row['bytes']>MAX_FILE:raise ValueError('Файл превышает 512 МиБ')
                if ident(path)!=row['identity']:raise ValueError('Файл изменился перед упаковкой')
                archive.write(path,Path(row['path']).as_posix())
                if ident(path)!=row['identity']:raise ValueError('Файл изменился при упаковке')
        return inspect(stage)
    try:
        try:summary=write_archive(zipfile.ZIP_DEFLATED)
        except CompressionRatioError:
            # Keep our own output within the same safety limits as incoming ZIPs.
            # Stored entries avoid a false positive without weakening extraction.
            summary=write_archive(zipfile.ZIP_STORED)
        check(stop);publish(stage,destination)
        return {'destination':str(destination),'entries':summary['entries'],'bytes':destination.stat().st_size}
    finally:stage.unlink(missing_ok=True)

class ArchiveCenter:
    def __init__(self,app):self.app=app;self.previews={};self.cancel=threading.Event()
    def preview(self,body):
        action=body.get('action')
        if action not in ('inspect','extract','create'):raise ValueError('Неизвестная операция ZIP')
        kind='folder' if action=='create' else 'file'
        path=self.app.toolbox.target(body,kind)
        if self.app.demo:
            result={'entries':2,'bytes':1024,'items':[{'name':'example.txt','size':1024}],'demo':True}
            identity=None
        else:
            identity=list(path.stat()[:2]) if kind=='folder' else ident(path)
            result={'entries':None,'bytes':None} if action=='create' else inspect(path)
        token=secrets.token_urlsafe(24)
        self.previews={token:{'path':path,'action':action,'expires':time.monotonic()+120,'identity':identity,'selection':body.get('selection')}}
        return {**result,'token':token,'action':action,'name':path.name}
    def run(self,body):
        if body.get('confirmed') is not True:raise ValueError('Подтвердите операцию ZIP')
        job=self.previews.pop(body.get('token'),None) if isinstance(body.get('token'),str) else None
        if not job or time.monotonic()>job['expires']:raise ValueError('Предпросмотр ZIP устарел')
        if job['action'] not in ('create','extract'):raise ValueError('Просмотр ZIP не разрешает распаковку')
        if self.app.demo:return {'message':'Демо: файлы не изменялись','demo':True}
        path=self.app.toolbox.target({'selection':job['selection']},'folder' if job['action']=='create' else 'file')
        if job['action']!='create' and ident(path)!=job['identity']:raise ValueError('Архив изменился после просмотра')
        result=create(path,self.cancel) if job['action']=='create' else extract(path,self.cancel)
        return {**result,'message':'Операция ZIP завершена'}
