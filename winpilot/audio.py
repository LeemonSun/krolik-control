"""Documented Windows Core Audio endpoint volume, no third-party modules."""
import ctypes as C
import os
import uuid
from contextlib import contextmanager

LONG=C.c_int32
DWORD=C.c_uint32
class GUID(C.Structure):
    _fields_=[('a',DWORD),('b',C.c_uint16),('c',C.c_uint16),('d',C.c_ubyte*8)]
def guid(value): return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
class PROPERTYKEY(C.Structure):
    _fields_=[('fmtid',GUID),('pid',DWORD)]
class PROPVARIANTDATA(C.Union):
    _fields_=[('text',C.c_wchar_p),('pointer',C.c_void_p),('data',C.c_ubyte*(2*C.sizeof(C.c_void_p))),('integer',C.c_int64)]
class PROPVARIANT(C.Structure):
    _anonymous_=('value',)
    _fields_=[('vt',C.c_uint16),('r1',C.c_uint16),('r2',C.c_uint16),('r3',C.c_uint16),('value',PROPVARIANTDATA)]
CLSID=guid('BCDE0395-E52F-467C-8E3D-C4579291692E')
IID_ENUM=guid('A95664D2-9614-4F35-A746-DE8DB63617E6')
IID_VOLUME=guid('5CDF2C82-841E-4546-9722-0CF74078229A')
FRIENDLY=PROPERTYKEY(guid('A45C254E-DF1C-4EFD-8020-67D146A850E0'),14)
FORM_FACTOR=PROPERTYKEY(guid('1DA5D803-D492-4EDD-8C23-E0C0FFE09C5F'),0)

def check(hr):
    if hr<0: raise OSError(f'Core Audio HRESULT: 0x{hr & 0xffffffff:08X}')

def call(ptr,index,types,*args):
    table=C.cast(ptr,C.POINTER(C.POINTER(C.c_void_p))).contents
    fn=C.WINFUNCTYPE(LONG,C.c_void_p,*types)(table[index])
    return fn(ptr,*args)

def release(ptr):
    if ptr: call(ptr,2,[])

@contextmanager
def enumerator():
    if os.name!='nt': raise RuntimeError('Core Audio доступен в Windows')
    ole=C.OleDLL('ole32')
    ole.CoInitializeEx.argtypes=[C.c_void_p,DWORD];ole.CoInitializeEx.restype=LONG
    ole.CoCreateInstance.argtypes=[C.POINTER(GUID),C.c_void_p,DWORD,C.POINTER(GUID),C.POINTER(C.c_void_p)];ole.CoCreateInstance.restype=LONG
    ole.CoTaskMemFree.argtypes=[C.c_void_p];ole.CoTaskMemFree.restype=None
    ole.CoUninitialize.argtypes=[];ole.CoUninitialize.restype=None
    ole.PropVariantClear.argtypes=[C.POINTER(PROPVARIANT)];ole.PropVariantClear.restype=LONG
    hr=ole.CoInitializeEx(None,0)
    check(hr)
    enum=C.c_void_p()
    try:
        check(ole.CoCreateInstance(C.byref(CLSID),None,23,C.byref(IID_ENUM),C.byref(enum)))
        yield enum,ole
    finally:
        release(enum);ole.CoUninitialize()

def device_id(device,ole):
    ptr=C.c_void_p()
    check(call(device,5,[C.POINTER(C.c_void_p)],C.byref(ptr)))
    try:return C.wstring_at(ptr)
    finally:ole.CoTaskMemFree(ptr)

def friendly_name(device,ole):
    store=C.c_void_p();pv=PROPVARIANT()
    try:
        check(call(device,4,[DWORD,C.POINTER(C.c_void_p)],0,C.byref(store)))
        check(call(store,5,[C.POINTER(PROPERTYKEY),C.POINTER(PROPVARIANT)],C.byref(FRIENDLY),C.byref(pv)))
        return pv.text if pv.vt==31 else 'Аудиоустройство'
    finally:
        ole.PropVariantClear(C.byref(pv));release(store)

def form_factor(device,ole):
    store=C.c_void_p();pv=PROPVARIANT()
    try:
        check(call(device,4,[DWORD,C.POINTER(C.c_void_p)],0,C.byref(store)))
        check(call(store,5,[C.POINTER(PROPERTYKEY),C.POINTER(PROPVARIANT)],C.byref(FORM_FACTOR),C.byref(pv)))
        value=int(pv.integer)&0xffffffff
        return value if pv.vt==19 and 0<=value<=10 else None
    except OSError:return None
    finally:ole.PropVariantClear(C.byref(pv));release(store)

@contextmanager
def volume_interface(device):
    volume=C.c_void_p()
    check(call(device,3,[C.POINTER(GUID),DWORD,C.c_void_p,C.POINTER(C.c_void_p)],C.byref(IID_VOLUME),23,None,C.byref(volume)))
    try:yield volume
    finally:release(volume)

def read_volume(volume):
    scalar=C.c_float();muted=LONG()
    check(call(volume,9,[C.POINTER(C.c_float)],C.byref(scalar)))
    check(call(volume,15,[C.POINTER(LONG)],C.byref(muted)))
    return {'scalar':scalar.value,'volume':round(scalar.value*100),'mute':bool(muted.value)}

def enumerate_audio():
    result=[]
    with enumerator() as (enum,ole):
        for flow in (0,1):
            defaults={}
            for role in (0,1,2):
                default=C.c_void_p()
                try:
                    if call(enum,4,[C.c_int,C.c_int,C.POINTER(C.c_void_p)],flow,role,C.byref(default))>=0:defaults[role]=device_id(default,ole)
                finally:release(default)
            default_id=defaults.get(1)
            collection=C.c_void_p()
            try:
                check(call(enum,3,[C.c_int,DWORD,C.POINTER(C.c_void_p)],flow,1,C.byref(collection)))
                count=DWORD();check(call(collection,3,[C.POINTER(DWORD)],C.byref(count)))
                for i in range(count.value):
                    device=C.c_void_p()
                    try:
                        check(call(collection,4,[DWORD,C.POINTER(C.c_void_p)],i,C.byref(device)))
                        ident=device_id(device,ole)
                        row={'id':ident,'name':friendly_name(device,ole),'flow':flow,'default':ident==default_id,'default_roles':[r for r,v in defaults.items() if v==ident],'controllable':False,'form_factor':form_factor(device,ole)}
                        try:
                            with volume_interface(device) as vol:row.update(read_volume(vol));row['controllable']=True
                        except OSError: pass
                        result.append(row)
                    finally:release(device)
            finally:release(collection)
    return result

@contextmanager
def endpoint_volume(ident):
    with enumerator() as (enum,ole):
        device=C.c_void_p()
        try:
            check(call(enum,5,[C.c_wchar_p,C.POINTER(C.c_void_p)],ident,C.byref(device)))
            with volume_interface(device) as volume:yield volume
        finally:release(device)

def get_endpoint(ident):
    with endpoint_volume(ident) as volume:return read_volume(volume)

def set_endpoint(ident,volume=None,mute=None,scalar=None):
    with endpoint_volume(ident) as interface:
        if volume is not None or scalar is not None:
            v=scalar if scalar is not None else volume/100
            if not 0<=v<=1:raise ValueError('Громкость вне диапазона')
            check(call(interface,7,[C.c_float,C.c_void_p],v,None))
        if mute is not None:check(call(interface,14,[LONG,C.c_void_p],int(mute),None))

IID_SESSIONS=guid('77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F')
IID_CONTROL2=guid('BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D')
IID_SIMPLE=guid('87CE5498-68D6-44E5-9215-6DA47EF883D8')

@contextmanager
def queried(pointer,iid):
    out=C.c_void_p();check(call(pointer,0,[C.POINTER(GUID),C.POINTER(C.c_void_p)],C.byref(iid),C.byref(out)))
    try:yield out
    finally:release(out)

def _session_rows(visitor):
    from .audio_tools import activated
    result=[]
    with enumerator() as (enum,ole):
        collection=C.c_void_p();check(call(enum,3,[C.c_int,DWORD,C.POINTER(C.c_void_p)],0,1,C.byref(collection)))
        try:
            count=DWORD();check(call(collection,3,[C.POINTER(DWORD)],C.byref(count)))
            for i in range(count.value):
                device=C.c_void_p();check(call(collection,4,[DWORD,C.POINTER(C.c_void_p)],i,C.byref(device)))
                try:
                    eid=device_id(device,ole)
                    with activated(device,IID_SESSIONS) as manager:
                        sessions=C.c_void_p();check(call(manager,5,[C.POINTER(C.c_void_p)],C.byref(sessions)))
                        try:
                            n=LONG();check(call(sessions,3,[C.POINTER(LONG)],C.byref(n)))
                            for j in range(n.value):
                                control=C.c_void_p();check(call(sessions,4,[C.c_int,C.POINTER(C.c_void_p)],j,C.byref(control)))
                                try:
                                    with queried(control,IID_CONTROL2) as ctl,queried(control,IID_SIMPLE) as volume:
                                        instance=C.c_void_p();pid=DWORD();state=LONG();check(call(ctl,13,[C.POINTER(C.c_void_p)],C.byref(instance)))
                                        try:sid=eid+'|'+C.wstring_at(instance)
                                        finally:ole.CoTaskMemFree(instance)
                                        check(call(ctl,14,[C.POINTER(DWORD)],C.byref(pid)));check(call(ctl,3,[C.POINTER(LONG)],C.byref(state)))
                                        if state.value==2:continue
                                        value=C.c_float();mute=LONG();check(call(volume,4,[C.POINTER(C.c_float)],C.byref(value)));check(call(volume,6,[C.POINTER(LONG)],C.byref(mute)))
                                        name='Системные звуки' if pid.value==0 else 'Приложение PID '+str(pid.value)
                                        kernel=C.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.argtypes=[DWORD,LONG,DWORD];kernel.OpenProcess.restype=C.c_void_p
                                        kernel.CloseHandle.argtypes=[C.c_void_p];kernel.QueryFullProcessImageNameW.argtypes=[C.c_void_p,DWORD,C.c_wchar_p,C.POINTER(DWORD)]
                                        handle=kernel.OpenProcess(0x1000,False,pid.value) if pid.value else None
                                        if handle:
                                            try:
                                                text=C.create_unicode_buffer(32768);length=DWORD(len(text))
                                                if kernel.QueryFullProcessImageNameW(handle,0,text,C.byref(length)):
                                                    from pathlib import PureWindowsPath
                                                    name=PureWindowsPath(text.value).stem
                                            finally:kernel.CloseHandle(handle)
                                        row={'id':sid,'name':name,'pid':pid.value,'volume':round(value.value*100),'mute':bool(mute.value),'active':state.value==1};visitor(row,volume);result.append(row)
                                finally:release(control)
                        finally:release(sessions)
                finally:release(device)
        finally:release(collection)
    return result

def audio_sessions():return _session_rows(lambda row,volume:None)

def set_session(ident,mute,volume):
    found=[]
    def change(row,pointer):
        if row['id']!=ident:return
        found.append(row);check(call(pointer,3,[C.c_float,C.c_void_p],volume/100,None));check(call(pointer,5,[LONG,C.c_void_p],int(mute),None))
        actual=C.c_float();muted=LONG();check(call(pointer,4,[C.POINTER(C.c_float)],C.byref(actual)));check(call(pointer,6,[C.POINTER(LONG)],C.byref(muted)))
        if abs(actual.value-volume/100)>.011 or bool(muted.value)!=mute:raise OSError('Громкость сессии не подтверждена')
    if type(mute)!=bool or type(volume) not in (int,float) or not __import__('math').isfinite(volume) or not 0<=volume<=100:raise ValueError('Некорректная громкость')
    _session_rows(change)
    if not found:raise ValueError('Аудиосессия уже закрыта')
