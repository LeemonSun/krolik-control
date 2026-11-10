"""Documented CCD APIs. Fixed-width ABI; no undocumented DPI setters."""
import ctypes as C
import os

U=C.c_uint32;I=C.c_int32
class LUID(C.Structure):_fields_=[('low',U),('high',I)]
class RATIONAL(C.Structure):_fields_=[('num',U),('den',U)]
class SOURCE(C.Structure):_fields_=[('adapter',LUID),('id',U),('mode',U),('status',U)]
class TARGET(C.Structure):_fields_=[('adapter',LUID),('id',U),('mode',U),('technology',U),('rotation',U),('scaling',U),('rate',RATIONAL),('scanline',U),('available',I),('status',U)]
class PATH(C.Structure):_fields_=[('source',SOURCE),('target',TARGET),('flags',U)]
class MODE_DATA(C.Union):_fields_=[('data',C.c_ubyte*48),('align',C.c_uint64)]
class MODE(C.Structure):_fields_=[('type',U),('id',U),('adapter',LUID),('data',MODE_DATA)]
class HEADER(C.Structure):_fields_=[('type',U),('size',U),('adapter',LUID),('id',U)]
class SOURCE_NAME(C.Structure):_fields_=[('header',HEADER),('name',C.c_uint16*32)]
class COLOR2(C.Structure):_fields_=[('header',HEADER),('flags',U),('encoding',U),('bits',U),('mode',U)]
class COLOR(C.Structure):_fields_=[('header',HEADER),('flags',U),('encoding',U),('bits',U)]
class SET_HDR(C.Structure):_fields_=[('header',HEADER),('enabled',U)]

def api():
    if os.name!='nt':raise ValueError('Нужна Windows')
    u=C.WinDLL('user32',use_last_error=True)
    u.GetDisplayConfigBufferSizes.argtypes=[U,C.POINTER(U),C.POINTER(U)]
    u.QueryDisplayConfig.argtypes=[U,C.POINTER(U),C.POINTER(PATH),C.POINTER(U),C.POINTER(MODE),C.POINTER(U)]
    u.SetDisplayConfig.argtypes=[U,C.POINTER(PATH),U,C.POINTER(MODE),U]
    u.DisplayConfigGetDeviceInfo.argtypes=[C.c_void_p];u.DisplayConfigSetDeviceInfo.argtypes=[C.c_void_p]
    return u

def query(u=None):
    u=u or api()
    for _ in range(4):
        pn=U();mn=U();code=u.GetDisplayConfigBufferSizes(2,C.byref(pn),C.byref(mn))
        if code:raise OSError(code,'Сведения экранов недоступны')
        if not 0<pn.value<=128 or not 0<mn.value<=384:raise ValueError('Неожиданный размер схемы экранов')
        paths=(PATH*pn.value)();modes=(MODE*mn.value)()
        code=u.QueryDisplayConfig(2,C.byref(pn),paths,C.byref(mn),modes,None)
        if code==122:continue
        if code:raise OSError(code,'Не удалось прочитать схему экранов')
        return u,paths,pn.value,modes,mn.value
    raise ValueError('Схема экранов меняется. Повторите проверку.')

def header(cls,typ,path):return HEADER(typ,C.sizeof(cls),path.target.adapter,path.target.id)
def source_name(u,path):
    s=SOURCE_NAME();s.header=HEADER(1,C.sizeof(s),path.source.adapter,path.source.id)
    if u.DisplayConfigGetDeviceInfo(C.byref(s)):return ''
    return bytes(s.name).decode('utf-16-le').split('\x00',1)[0]

def color(u,path):
    c=COLOR2();c.header=header(COLOR2,15,path)
    if u.DisplayConfigGetDeviceInfo(C.byref(c)):
        legacy=COLOR();legacy.header=header(COLOR,9,path)
        if u.DisplayConfigGetDeviceInfo(C.byref(legacy)):return {'hdr_available':False,'hdr_enabled':None,'hdr_reason':'Windows или драйвер не предоставили управление расширенным цветом'}
        return {'hdr_available':bool(legacy.flags&1 and not legacy.flags&8),'hdr_enabled':bool(legacy.flags&2),'bits':legacy.bits,'hdr_api':10,'control_label':'Расширенный цвет HDR/WCG','hdr_reason':'Windows сообщает об общем режиме расширенного цвета. Отдельные состояния HDR и широкого охвата не разделяются.'}
    return {'hdr_available':bool(c.flags&16 and not c.flags&8),'hdr_enabled':bool(c.flags&32),'bits':c.bits,'hdr_api':16,'control_label':'HDR','hdr_reason':'' if c.flags&16 and not c.flags&8 else 'HDR не поддерживается либо ограничен политикой'}

def inventory():
    u,p,n,_,_=query();out=[]
    for path in p[:n]:
        name=source_name(u,path)
        if name:out.append({'id':name,'refresh_num':path.target.rate.num,'refresh_den':path.target.rate.den,'refresh_hz':path.target.rate.num/path.target.rate.den if path.target.rate.den else None,**color(u,path)})
    return out

def hdr_begin(device,enabled):
    if type(enabled)!=bool:raise ValueError('Некорректное состояние HDR')
    u,paths,n,_,_=query();matches=[p for p in paths[:n] if source_name(u,p)==device]
    if len(matches)!=1:raise ValueError('Для HDR выберите отдельный активный экран без дублирования')
    path=matches[0];old=color(u,path)
    if not old['hdr_available'] or type(old['hdr_enabled'])!=bool:raise ValueError(old['hdr_reason'])
    adapter=(path.target.adapter.low,path.target.adapter.high,path.target.id)
    def set_value(value):
        uu,pp,count,_,_=query();live=[p for p in pp[:count] if (p.target.adapter.low,p.target.adapter.high,p.target.id)==adapter and source_name(uu,p)==device]
        if len(live)!=1:raise ValueError('Экран отключён или изменился')
        arg=SET_HDR();arg.header=header(SET_HDR,old.get('hdr_api',16),live[0]);arg.enabled=int(value)
        code=uu.DisplayConfigSetDeviceInfo(C.byref(arg))
        if code:raise OSError(code,'Драйвер отклонил HDR')
        return uu,live[0]
    set_value(enabled)
    def resolve(keep):
        if not keep:set_value(old['hdr_enabled']);return
        uu,pp,count,_,_=query();live=[p for p in pp[:count] if source_name(uu,p)==device]
        if len(live)!=1 or color(uu,live[0])['hdr_enabled']!=enabled:
            set_value(old['hdr_enabled']);raise ValueError('HDR не подтверждён чтением')
    return resolve

def topology_begin(kind):
    flags={'extend':4,'clone':2,'internal':1,'external':8}
    if kind not in flags:raise ValueError('Неизвестная схема экранов')
    u,paths,n,modes,m=query()
    code=u.SetDisplayConfig(0,None,0,None,flags[kind]|0x80)
    if code:raise OSError(code,'Драйвер отклонил схему экранов')
    def resolve(keep):
        if keep:
            # Commit the currently accepted topology using explicit supplied paths.
            uu,pp,nn,mm,nm=query();code=uu.SetDisplayConfig(nn,pp,nm,mm,0x20|0x80|0x200)
        else:code=u.SetDisplayConfig(n,paths,m,modes,0x20|0x80)
        if code:
            if keep:u.SetDisplayConfig(n,paths,m,modes,0x20|0x80)
            raise OSError(code,'Не удалось сохранить или вернуть схему экранов')
    return resolve
