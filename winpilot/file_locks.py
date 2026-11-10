"""Documented Restart Manager read-only file owners. Never closes handles."""
import ctypes as C
import os
D=C.c_uint32;W=C.c_uint16
class TIME(C.Structure):_fields_=[('lo',D),('hi',D)]
class PROCESS(C.Structure):_fields_=[('pid',D),('started',TIME)]
class INFO(C.Structure):_fields_=[('process',PROCESS),('name',W*256),('service',W*64),('kind',D),('status',D),('session',D),('restartable',D)]
def text(a):return bytes(a).decode('utf-16-le').split('\0',1)[0]
def owners(path):
    if os.name!='nt':raise ValueError('Проверка блокировки доступна в Windows')
    r=C.WinDLL('rstrtmgr');r.RmStartSession.argtypes=[C.POINTER(D),D,C.c_wchar_p];r.RmRegisterResources.argtypes=[D,D,C.POINTER(C.c_wchar_p),D,C.c_void_p,D,C.c_void_p];r.RmGetList.argtypes=[D,C.POINTER(D),C.POINTER(D),C.POINTER(INFO),C.POINTER(D)];r.RmEndSession.argtypes=[D]
    session=D();key=C.create_unicode_buffer(33);code=r.RmStartSession(C.byref(session),0,key)
    if code:raise OSError(code,'Проверка блокировок недоступна')
    try:
        files=(C.c_wchar_p*1)(str(path));code=r.RmRegisterResources(session,1,files,0,None,0,None)
        if code:raise OSError(code,'Не удалось зарегистрировать выбранный файл')
        for _ in range(4):
            required=D();count=D();reason=D();code=r.RmGetList(session,C.byref(required),C.byref(count),None,C.byref(reason))
            if code==0 and required.value==0:return []
            if code not in (0,234) or required.value>256:raise OSError(code,'Слишком большой или недоступный список процессов')
            rows=(INFO*required.value)();count=D(required.value);code=r.RmGetList(session,C.byref(required),C.byref(count),rows,C.byref(reason))
            if code==234:continue
            if code:raise OSError(code,'Не удалось прочитать владельцев файла')
            return [{'pid':x.process.pid,'name':text(x.name),'service':text(x.service),'restartable':bool(x.restartable)} for x in rows[:count.value]]
        raise ValueError('Список процессов меняется. Повторите проверку.')
    finally:r.RmEndSession(session)
