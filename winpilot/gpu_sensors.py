"""Read-only NVML driver metrics. No driver or service is installed."""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys

class MEMORY(C.Structure):_fields_=[('total',C.c_uint64),('free',C.c_uint64),('used',C.c_uint64)]
class USAGE(C.Structure):_fields_=[('gpu',C.c_uint32),('memory',C.c_uint32)]

def system_directory():
 k=C.WinDLL('kernel32',use_last_error=True);k.GetSystemDirectoryW.argtypes=[C.c_wchar_p,C.c_uint32];b=C.create_unicode_buffer(32768);n=k.GetSystemDirectoryW(b,len(b))
 if not n or n>=len(b):raise ValueError('Каталог Windows недоступен')
 return Path(b.value)

class NVML:
 def __init__(self):
  self.dll=None;self.available=False
  paths=[system_directory()/'nvml.dll']
  try:
   import winreg as R
   with R.OpenKey(R.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows\CurrentVersion',0,R.KEY_READ|R.KEY_WOW64_64KEY) as key:paths.append(Path(R.QueryValueEx(key,'ProgramFilesDir')[0])/'NVIDIA Corporation/NVSMI/nvml.dll')
  except OSError:pass
  for p in paths:
   if not p.is_file():continue
   # Both locations are administrator-managed. Dependencies use those locations and System32.
   from .trust import verify
   verify(p)
   self.dll=C.WinDLL(str(p),winmode=0x100|0x800);break
  if not self.dll:return
  self.dll.nvmlInit_v2.argtypes=[];self.dll.nvmlInit_v2.restype=C.c_int
  self.available=self.dll.nvmlInit_v2()==0
 def fn(self,name,args):
  f=getattr(self.dll,name,None)
  if f:f.argtypes=args;f.restype=C.c_int
  return f
 def read(self):
  if not self.available:return []
  count=C.c_uint32();f=self.fn('nvmlDeviceGetCount_v2',[C.POINTER(C.c_uint32)])
  if not f or f(C.byref(count)):return []
  handle=self.fn('nvmlDeviceGetHandleByIndex_v2',[C.c_uint32,C.POINTER(C.c_void_p)]);out=[]
  for i in range(min(count.value,16)):
   h=C.c_void_p()
   if not handle or handle(i,C.byref(h)):continue
   row={'source':'NVML','vendor':'NVIDIA'}
   for field,name in [('name','nvmlDeviceGetName'),('key','nvmlDeviceGetUUID')]:
    buf=C.create_string_buffer(256);fn=self.fn(name,[C.c_void_p,C.c_char_p,C.c_uint32])
    row[field]=buf.value.decode('utf-8',errors='replace') if fn and not fn(h,buf,len(buf)) else None
   def metric(name,args,low,high):
    fn=self.fn(name,[C.c_void_p,*[C.c_uint32 for _ in args],C.POINTER(C.c_uint32)]);v=C.c_uint32()
    return v.value if fn and not fn(h,*args,C.byref(v)) and low<=v.value<=high else None
   row['temperature_c']=metric('nvmlDeviceGetTemperature',[0],0,150);row['core_mhz']=metric('nvmlDeviceGetClockInfo',[0],0,20000);row['memory_mhz']=metric('nvmlDeviceGetClockInfo',[2],0,50000);row['fan_percent']=metric('nvmlDeviceGetFanSpeed',[],0,100);row['power_mw']=metric('nvmlDeviceGetPowerUsage',[],0,2000000)
   usage=USAGE();fn=self.fn('nvmlDeviceGetUtilizationRates',[C.c_void_p,C.POINTER(USAGE)]);row['load']=usage.gpu if fn and not fn(h,C.byref(usage)) and usage.gpu<=100 else None
   memory=MEMORY();fn=self.fn('nvmlDeviceGetMemoryInfo',[C.c_void_p,C.POINTER(MEMORY)])
   if fn and not fn(h,C.byref(memory)) and 0<memory.total<=1024**4 and memory.used<=memory.total:row.update(vram_used_bytes=memory.used,vram_total_bytes=memory.total)
   reason=C.c_uint64();fn=self.fn('nvmlDeviceGetCurrentClocksEventReasons',[C.c_void_p,C.POINTER(C.c_uint64)]) or self.fn('nvmlDeviceGetCurrentClocksThrottleReasons',[C.c_void_p,C.POINTER(C.c_uint64)])
   row['clock_limit_bits']=str(reason.value) if fn and not fn(h,C.byref(reason)) else None
   out.append(row)
  return out
 def close(self):
  if self.available:
   f=self.fn('nvmlShutdown',[])
   if f:f()
  self.available=False

def once(provider):
 rows=provider.read();helper=Path(__file__).resolve().parents[1]/'krolik-adl.exe'
 if helper.is_file():
  try:
   r=subprocess.run([str(helper),str(os.getpid())],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,creationflags=0x08000000)
   if r.returncode==0 and len(r.stdout)<131072:
    a=json.loads(r.stdout.decode('utf-8'))
    if isinstance(a,list):rows+=a[:16]
  except (OSError,ValueError,subprocess.TimeoutExpired):pass
 return {'gpu_details':rows}

def main():
 parent=None;provider=None;k=None
 try:
  if os.name!='nt':raise ValueError('Нужна Windows')
  if len(sys.argv)==2:
   k=C.WinDLL('kernel32');k.OpenProcess.argtypes=[C.c_uint32,C.c_int,C.c_uint32];k.OpenProcess.restype=C.c_void_p;k.WaitForSingleObject.argtypes=[C.c_void_p,C.c_uint32];k.CloseHandle.argtypes=[C.c_void_p];parent=k.OpenProcess(0x100000,False,int(sys.argv[1]))
   if not parent:return 1
  try:provider=NVML()
  except (OSError,AttributeError,ValueError):provider=None
  if provider is None:
   class Empty:
    def read(self):return []
    def close(self):pass
   provider=Empty()
  while True:
   if parent and k.WaitForSingleObject(parent,0)!=258:break
   print(json.dumps(once(provider)),flush=True)
   if not parent:break
   if k.WaitForSingleObject(parent,3000)!=258:break
  return 0
 finally:
  if provider:provider.close()
  if parent:k.CloseHandle(parent)
if __name__=='__main__':raise SystemExit(main())
