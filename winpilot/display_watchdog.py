"""Independent CCD rollback process. It is armed before any display mutation."""
import base64
import ctypes as C
import functools
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading

WAIT_OBJECT_0=0;WAIT_TIMEOUT=258

def kernel():
 k=C.WinDLL('kernel32',use_last_error=True)
 k.CreateEventW.argtypes=[C.c_void_p,C.c_int,C.c_int,C.c_wchar_p];k.CreateEventW.restype=C.c_void_p
 k.OpenEventW.argtypes=[C.c_uint32,C.c_int,C.c_wchar_p];k.OpenEventW.restype=C.c_void_p
 k.SetEvent.argtypes=[C.c_void_p];k.CloseHandle.argtypes=[C.c_void_p]
 k.OpenProcess.argtypes=[C.c_uint32,C.c_int,C.c_uint32];k.OpenProcess.restype=C.c_void_p
 k.WaitForMultipleObjects.argtypes=[C.c_uint32,C.POINTER(C.c_void_p),C.c_int,C.c_uint32];k.WaitForMultipleObjects.restype=C.c_uint32
 return k

def capture():
 from .display_advanced import query,color,source_name
 u,p,n,m,nm=query();hdr=[]
 for row in p[:n]:
  c=color(u,row)
  if c.get('hdr_available') and type(c.get('hdr_enabled'))==bool:hdr.append({'id':source_name(u,row),'enabled':c['hdr_enabled']})
 return {'paths':base64.b64encode(bytes(p)[:n*C.sizeof(p._type_)]).decode(),'modes':base64.b64encode(bytes(m)[:nm*C.sizeof(m._type_)]).decode(),'hdr':hdr}

def decode(snapshot):
 from .display_advanced import PATH,MODE
 if not isinstance(snapshot,dict):raise ValueError('Invalid snapshot')
 p=base64.b64decode(snapshot['paths'],validate=True);m=base64.b64decode(snapshot['modes'],validate=True)
 if not p or len(p)%C.sizeof(PATH) or len(p)>128*C.sizeof(PATH) or not m or len(m)%C.sizeof(MODE) or len(m)>384*C.sizeof(MODE):raise ValueError('Invalid CCD bounds')
 return (PATH*(len(p)//C.sizeof(PATH))).from_buffer_copy(p),(MODE*(len(m)//C.sizeof(MODE))).from_buffer_copy(m)

def restore(snapshot):
 from .display_advanced import api,hdr_begin
 paths,modes=decode(snapshot);u=api();code=u.SetDisplayConfig(len(paths),paths,len(modes),modes,0x20|0x80|0x200)
 if code:raise OSError(code,'Не удалось вернуть схему экранов')
 errors=[]
 for r in snapshot.get('hdr',[])[:128]:
  try:hdr_begin(r['id'],r['enabled'])(True)
  except Exception as e:errors.append(str(e))
 if errors:raise ValueError('Не все параметры HDR удалось вернуть: '+'; '.join(errors)[:500])

class Watchdog:
 def __init__(self):
  self.k=kernel();self.handles=[];self.process=None;self.finished=False
  try:
   names=['Local\\KrolikDisplay-'+secrets.token_hex(24) for _ in range(2)]
   for name in names:
    h=self.k.CreateEventW(None,True,False,name)
    if not h:raise OSError(C.get_last_error(),'Не удалось подготовить возврат экрана')
    self.handles.append(h)
   snapshot=capture();decode(snapshot)
   from .worker_process import worker_command
   self.process=subprocess.Popen(worker_command('display_watchdog'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=0x08000000)
   self.process.stdin.write(json.dumps({'parent':os.getpid(),'events':names,'snapshot':snapshot}).encode()+b'\n');self.process.stdin.flush();self.process.stdin.close();self.process.stdin=None
   ready=queue.Queue(maxsize=1)
   threading.Thread(target=lambda:ready.put(self.process.stdout.readline(256)),daemon=True).start()
   try:line=ready.get(timeout=4)
   except queue.Empty:raise ValueError('Защита экрана не запустилась; изменение отменено') from None
   if line.strip()!=b'ready':raise ValueError('Защита экрана не подтвердила готовность; изменение отменено')
  except BaseException:
   if self.process and self.process.poll() is None:self.process.kill();self.process.wait(timeout=2)
   self.close();raise
 def close(self):
  for h in self.handles:self.k.CloseHandle(h)
  self.handles=[]
  if self.process and self.process.poll() is not None and self.process.stdout:self.process.stdout.close()
 def finish(self,keep):
  if self.finished:return False
  self.finished=True;ok=False
  try:
   if self.process.poll() is not None:return False
   if not self.k.SetEvent(self.handles[0 if keep else 1]):return False
   try:out,_=self.process.communicate(timeout=4)
   except subprocess.TimeoutExpired:
    # Never kill an armed rollback helper. Ask it to restore and let it finish.
    self.k.SetEvent(self.handles[1]);return False
   try:result=json.loads(out.decode('utf-8'))
   except (ValueError,UnicodeError):return False
   ok=self.process.returncode==0 and result.get('kept')==bool(keep) and result.get('ok') is True
   return ok
  finally:self.close()

def crash_guarded(fn):
 @functools.wraps(fn)
 def guarded(self,*args,**kwargs):
  from .native import IS_WINDOWS
  with self.lock:
   if self.pending:raise ValueError('Сначала подтвердите предыдущий режим экрана')
   w=Watchdog() if IS_WINDOWS else None
   try:
    ident=fn(self,*args,**kwargs)
    if w:self.pending['watchdog']=w
    return ident
   except BaseException:
    if w:w.finish(False)
    raise
 return guarded

def worker():
 k=kernel();handles=[];parent=None
 try:
  raw=sys.stdin.buffer.readline(150000)
  if len(raw)>=150000:raise ValueError('Snapshot too large')
  job=json.loads(raw);snapshot=job['snapshot'];decode(snapshot);names=job['events'];pid=job['parent']
  if type(pid)!=int or pid<1 or not isinstance(names,list) or len(names)!=2 or any(not isinstance(n,str) or not __import__('re').fullmatch(r'Local\\KrolikDisplay-[a-f0-9]{48}',n) for n in names):raise ValueError('Invalid watchdog parameters')
  parent=k.OpenProcess(0x100000,False,pid)
  if not parent:raise ValueError('Parent unavailable')
  for name in names:
   h=k.OpenEventW(0x100000,False,name)
   if not h:raise ValueError('Decision event unavailable')
   handles.append(h)
  print('ready',flush=True)
  targets=(C.c_void_p*3)(parent,*handles);result=k.WaitForMultipleObjects(3,targets,False,25000)
  keep=result==1
  if not keep:restore(snapshot)
  print(json.dumps({'ok':True,'kept':keep}),flush=True)
  return 0
 except BaseException as e:
  try:print(json.dumps({'ok':False,'kept':False,'error':str(e)[:400]}),flush=True)
  except OSError:pass
  return 1
 finally:
  for h in handles:k.CloseHandle(h)
  if parent:k.CloseHandle(parent)
if __name__=='__main__':raise SystemExit(worker())
