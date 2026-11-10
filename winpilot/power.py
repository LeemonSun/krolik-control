"""Temporary native power request, released at expiry or process exit."""
import ctypes as C
import os
import threading
import time
class PowerLease:
    def __init__(self):self.lock=threading.RLock();self.handle=None;self.expires=0;self.display=False;self.timer=None;self.generation=0
    def state(self):
        with self.lock:return {'active':bool(self.handle),'seconds':max(0,round(self.expires-time.monotonic())) if self.handle else 0,'display':self.display}
    def start(self,minutes,display=False,demo=False):
        if type(minutes)!=int or minutes not in (15,30,60,120,360) or type(display)!=bool:raise ValueError('Выберите 15–360 минут')
        with self.lock:
            self.close();self.display=display
            if demo:self.handle='demo'
            elif os.name=='nt':
                class REASON(C.Union):_fields_=[('text',C.c_wchar_p),('reserved',C.c_uint64*3)]
                class CONTEXT(C.Structure):_fields_=[('version',C.c_uint32),('flags',C.c_uint32),('reason',REASON)]
                k=C.WinDLL('kernel32',use_last_error=True);k.PowerCreateRequest.argtypes=[C.POINTER(CONTEXT)];k.PowerCreateRequest.restype=C.c_void_p;k.PowerSetRequest.argtypes=[C.c_void_p,C.c_int];k.CloseHandle.argtypes=[C.c_void_p]
                reason=CONTEXT();reason.flags=1;reason.reason.text='Krolik Control: временная задача';h=k.PowerCreateRequest(C.byref(reason))
                if h in (None,C.c_void_p(-1).value):raise OSError(C.get_last_error(),'Windows отклонила запрос питания')
                if not k.PowerSetRequest(h,1) or display and not k.PowerSetRequest(h,0):k.CloseHandle(h);raise OSError(C.get_last_error(),'Windows не удержала режим питания')
                self.handle=h
            else:raise ValueError('Доступно в Windows')
            self.expires=time.monotonic()+minutes*60;self.timer=threading.Timer(minutes*60,self._expire,args=(self.generation,));self.timer.daemon=True;self.timer.start();return self.state()
    def _expire(self,generation):
        with self.lock:
            if generation==self.generation:self.close()
    def close(self):
        with self.lock:
            self.generation+=1
            if self.timer:self.timer.cancel();self.timer=None
            if self.handle and self.handle!='demo':
                k=C.WinDLL('kernel32');k.CloseHandle.argtypes=[C.c_void_p];k.CloseHandle(self.handle)
            self.handle=None;self.expires=0
