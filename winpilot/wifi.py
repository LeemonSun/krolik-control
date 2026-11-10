"""Current Native Wi-Fi connection, requested explicitly. SSIDs are untrusted text."""
import ctypes as C
import os
from .audio import GUID
D=C.c_uint32;W=C.c_uint16
class INTERFACE(C.Structure):_fields_=[('guid',GUID),('description',W*256),('state',D)]
class SSID(C.Structure):_fields_=[('length',D),('value',C.c_ubyte*32)]
class ASSOCIATION(C.Structure):_fields_=[('ssid',SSID),('bss',D),('bssid',C.c_ubyte*6),('phy',D),('index',D),('quality',D),('rx',D),('tx',D)]
class SECURITY(C.Structure):_fields_=[('enabled',D),('one_x',D),('auth',D),('cipher',D)]
class CONNECTION(C.Structure):_fields_=[('state',D),('mode',D),('profile',W*256),('association',ASSOCIATION),('security',SECURITY)]
def text(a):return bytes(a).decode('utf-16-le').split('\0',1)[0]
def current():
    if os.name!='nt':raise ValueError('Требуется Windows')
    w=C.WinDLL('wlanapi');w.WlanOpenHandle.argtypes=[D,C.c_void_p,C.POINTER(D),C.POINTER(C.c_void_p)];w.WlanEnumInterfaces.argtypes=[C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)];w.WlanQueryInterface.argtypes=[C.c_void_p,C.POINTER(GUID),D,C.c_void_p,C.POINTER(D),C.POINTER(C.c_void_p),C.c_void_p];w.WlanFreeMemory.argtypes=[C.c_void_p];w.WlanCloseHandle.argtypes=[C.c_void_p,C.c_void_p]
    version=D();handle=C.c_void_p();code=w.WlanOpenHandle(2,None,C.byref(version),C.byref(handle))
    if code:raise OSError(code,'Служба Wi-Fi недоступна')
    pointer=C.c_void_p();result=[]
    try:
        code=w.WlanEnumInterfaces(handle,None,C.byref(pointer))
        if code:raise OSError(code,'Не удалось прочитать адаптеры Wi-Fi')
        count=C.cast(pointer,C.POINTER(D))[0]
        if count>32:raise ValueError('Слишком много Wi-Fi интерфейсов')
        interfaces=C.cast(pointer.value+8,C.POINTER(INTERFACE))
        for row in interfaces[:count]:
            out={'name':text(row.description),'connected':row.state==1};size=D();data=C.c_void_p()
            if row.state!=1:result.append(out);continue
            code=w.WlanQueryInterface(handle,C.byref(row.guid),7,None,C.byref(size),C.byref(data),None)
            try:
                if code:out.update(available=False,reason='Windows ограничивает Wi-Fi-сведения разрешением местоположения' if code==5 else 'Драйвер не предоставил параметры соединения')
                elif size.value<C.sizeof(CONNECTION):out.update(available=False,reason='Неизвестный формат соединения')
                else:
                    info=C.cast(data,C.POINTER(CONNECTION)).contents;a=info.association
                    if a.ssid.length>32:raise ValueError('Неверная длина SSID')
                    out.update(available=True,ssid=bytes(a.ssid.value[:a.ssid.length]).decode('utf-8',errors='replace'),quality=min(a.quality,100),rx_link_mbps=round(a.rx/1000,1),tx_link_mbps=round(a.tx/1000,1),security=bool(info.security.enabled))
            finally:
                if data:w.WlanFreeMemory(data)
            result.append(out)
        return result
    finally:
        if pointer:w.WlanFreeMemory(pointer)
        w.WlanCloseHandle(handle,None)
