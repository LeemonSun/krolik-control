"""Opt-in cleanup of old current-user temp files, with a fixed scope and preview."""
import ctypes as C
import os
from pathlib import Path
import secrets
import stat
import threading
import time

def linked(path):
    try:return path.is_symlink() or bool(path.lstat().st_file_attributes&0x400) if os.name=='nt' else path.is_symlink()
    except OSError:return True

def identity(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or linked(path):raise ValueError('Не обычный файл')
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)

def _windows_delete(path,root,expected):
    """Delete the inspected object by its handle, never follow a replaced final link."""
    from ctypes import wintypes as W
    class FILETIME(C.Structure):_fields_=[('lo',W.DWORD),('hi',W.DWORD)]
    class INFO(C.Structure):
        _fields_=[('attributes',W.DWORD),('created',FILETIME),('accessed',FILETIME),('written',FILETIME),('volume',W.DWORD),('size_hi',W.DWORD),('size_lo',W.DWORD),('links',W.DWORD),('index_hi',W.DWORD),('index_lo',W.DWORD)]
    k=C.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE];k.CreateFileW.restype=W.HANDLE
    k.GetFinalPathNameByHandleW.argtypes=[W.HANDLE,W.LPWSTR,W.DWORD,W.DWORD]
    k.GetFileInformationByHandle.argtypes=[W.HANDLE,C.POINTER(INFO)]
    k.SetFileInformationByHandle.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD]
    k.CloseHandle.argtypes=[W.HANDLE]
    h=k.CreateFileW(str(path),0x10000|0x80,7,None,3,0x00200000,None)
    if h==C.c_void_p(-1).value:raise OSError(C.get_last_error(),'Файл недоступен')
    try:
        b=C.create_unicode_buffer(32768);n=k.GetFinalPathNameByHandleW(h,b,len(b),0)
        if not n or n>=len(b):raise OSError('Не удалось проверить путь')
        final=Path(b.value.removeprefix('\\\\?\\')).resolve()
        if root not in final.parents:raise ValueError('Файл перемещён за пределы временной папки')
        info=INFO()
        if not k.GetFileInformationByHandle(h,C.byref(info)) or info.attributes&0x410:raise ValueError('Файл изменился')
        size=(info.size_hi<<32)|info.size_lo;written=((info.written.hi<<32)|info.written.lo)*100-11644473600000000000
        if size!=expected[2] or abs(written-expected[3])>100 or ((info.index_hi<<32)|info.index_lo)!=expected[1]:raise ValueError('Файл изменился после просмотра')
        disposition=C.c_ubyte(1)
        if not k.SetFileInformationByHandle(h,4,C.byref(disposition),C.sizeof(disposition)):raise OSError(C.get_last_error(),'Удаление не выполнено')
    finally:k.CloseHandle(h)

class StorageCenter:
    def __init__(self,app,root=None):
        self.app=app;self.lock=threading.RLock();self.pending=None;self.snapshot=None
        self.root=Path(root) if root else (Path(os.environ['LOCALAPPDATA'])/'Temp' if os.name=='nt' else None)
    def scan(self):
        if self.app.demo:
            self.snapshot={'token':secrets.token_urlsafe(24),'expires':time.monotonic()+120,'rows':[]}
            return {'token':self.snapshot['token'],'files':42,'bytes':180*1024**2,'scope':'Временные файлы пользователя старше 7 дней','demo':True,'limited':False}
        if self.root is None or not self.root.is_dir() or linked(self.root):raise ValueError('Временная папка пользователя недоступна')
        root=self.root.resolve();cutoff=time.time()-7*86400;rows=[];seen=0;limited=False
        for base,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if not linked(Path(base)/d)]
            if linked(Path(base)):
                dirs.clear();continue
            for name in names:
                seen+=1
                if seen>20000:limited=True;break
                p=Path(base)/name
                try:
                    ident=identity(p)
                    if ident[3]/1e9>cutoff or ident[2]>1024**3 or root not in p.resolve().parents:continue
                    rows.append((str(p.relative_to(root)),ident))
                    if len(rows)>=5000:limited=True;break
                except (OSError,ValueError):continue
            if limited:break
        token=secrets.token_urlsafe(24)
        with self.lock:self.snapshot={'token':token,'expires':time.monotonic()+120,'root':str(root),'rows':rows}
        return {'token':token,'files':len(rows),'bytes':sum(r[1][2] for r in rows),'scope':'Временные файлы пользователя старше 7 дней','demo':False,'limited':limited,'examples':[r[0] for r in rows[:12]]}
    def consume(self,body):
        with self.lock:
            s=self.snapshot
            if not s or type(body.get('token'))!=str or not secrets.compare_digest(s['token'],body['token']) or time.monotonic()>s['expires']:raise ValueError('Список очистки устарел. Повторите просмотр.')
            if body.get('confirmed') is not True:raise ValueError('Подтвердите удаление временных файлов')
            self.snapshot=None;return s
    def clean(self,s):
        if self.app.demo:return {'deleted':42,'bytes':180*1024**2,'skipped':0,'demo':True}
        root=Path(s['root']);deleted=0;size=0;skipped=0
        if self.root.resolve()!=root or linked(self.root):raise ValueError('Временная папка изменилась')
        for name,expected in s['rows']:
            p=root/name
            try:
                parent=p.parent
                while parent!=root:
                    if linked(parent):raise ValueError('Папка стала ссылкой')
                    parent=parent.parent
                if identity(p)!=expected or root not in p.resolve().parents:raise ValueError('Файл изменился')
                if os.name=='nt':_windows_delete(p,root,expected)
                else:p.unlink()
                deleted+=1;size+=expected[2]
            except (OSError,ValueError):skipped+=1
        return {'deleted':deleted,'bytes':size,'skipped':skipped,'demo':False}
