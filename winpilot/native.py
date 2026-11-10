"""Documented Win32 display and input calls. Imported safely on non-Windows."""
import ctypes as C
import os
import threading
import time
import uuid

IS_WINDOWS = os.name == 'nt'
# Fixed-width types are intentional: c_long is 64-bit on Linux, Win32 LONG is 32.
DWORD=C.c_uint32
LONG=C.c_int32
WORD=C.c_uint16

class POINT(C.Structure):
    _fields_=[('x',LONG),('y',LONG)]
class DISPLAYUNION(C.Union):
    _fields_=[('data',C.c_byte*16),('display',type('Display', (C.Structure,), {'_fields_':[('position',POINT),('orientation',DWORD),('fixedOutput',DWORD)]}))]
class DEVMODE(C.Structure):
    _anonymous_=('u',)
    _fields_=[('device',C.c_wchar*32),('spec',WORD),('driver',WORD),('size',WORD),('extra',WORD),('fields',DWORD),('u',DISPLAYUNION),('color',C.c_int16),('duplex',C.c_int16),('yres',C.c_int16),('tt',C.c_int16),('collate',C.c_int16),('form',C.c_wchar*32),('dpi',WORD),('bpp',DWORD),('width',DWORD),('height',DWORD),('flags',DWORD),('hz',DWORD),('icm',DWORD),('intent',DWORD),('media',DWORD),('dither',DWORD),('reserved1',DWORD),('reserved2',DWORD),('panw',DWORD),('panh',DWORD)]
class DISPLAYDEVICE(C.Structure):
    _fields_=[('size',DWORD),('name',C.c_wchar*32),('description',C.c_wchar*128),('flags',DWORD),('id',C.c_wchar*128),('key',C.c_wchar*128)]

def user32():
    if not IS_WINDOWS:
        raise RuntimeError('Доступно только в Windows')
    u=C.WinDLL('user32',use_last_error=True)
    u.EnumDisplayDevicesW.argtypes=[C.c_wchar_p,DWORD,C.POINTER(DISPLAYDEVICE),DWORD]
    u.EnumDisplaySettingsW.argtypes=[C.c_wchar_p,DWORD,C.POINTER(DEVMODE)]
    u.ChangeDisplaySettingsExW.argtypes=[C.c_wchar_p,C.POINTER(DEVMODE),C.c_void_p,DWORD,C.c_void_p]
    u.ChangeDisplaySettingsExW.restype=LONG
    return u

def mode_at(u,device,index):
    dm=DEVMODE(); dm.size=C.sizeof(dm)
    return dm if u.EnumDisplaySettingsW(device,index & 0xffffffff,C.byref(dm)) else None

def enumerate_displays():
    u=user32(); result=[]; i=0
    while True:
        d=DISPLAYDEVICE(); d.size=C.sizeof(d)
        if not u.EnumDisplayDevicesW(None,i,C.byref(d),0): break
        i+=1
        if not d.flags & 1 or d.flags & 8: continue
        current=mode_at(u,d.name,-1)
        if current is None: continue
        monitor=DISPLAYDEVICE(); monitor.size=C.sizeof(monitor)
        u.EnumDisplayDevicesW(d.name,0,C.byref(monitor),0)
        modes={}; j=0
        while True:
            dm=mode_at(u,d.name,j)
            if dm is None: break
            j+=1
            if dm.bpp != 32 or dm.hz < 24: continue
            # Keep interlaced modes distinct; only expose progressive modes.
            if dm.flags & 2: continue
            if dm.display.orientation%2 != current.display.orientation%2:
                dm.width,dm.height=dm.height,dm.width
            key=f'{dm.width}x{dm.height}@{dm.hz}'
            modes[key]={'id':key,'width':dm.width,'height':dm.height,'hz':dm.hz}
        result.append({'id':d.name,'name':monitor.description or d.description,'gpu':d.description,
          'primary':bool(d.flags&4),'x':current.display.position.x,'y':current.display.position.y,
          'current':f'{current.width}x{current.height}@{current.hz}', 'orientation':int(current.display.orientation),
          'modes':sorted(modes.values(),key=lambda m:(m['width']*m['height'],m['hz']),reverse=True)})
    return result

from .display_watchdog import crash_guarded

class DisplayGuard:
    """One display change at a time. Timer restores it without the browser."""
    def __init__(self):
        self.lock=threading.RLock(); self.pending=None; self.result=None
    @crash_guarded
    def apply(self,device,mode,orientation):
        with self.lock:
            if self.pending: raise ValueError('Сначала подтвердите предыдущий режим экрана')
            u=user32(); old=mode_at(u,device,-1)
            if old is None: raise ValueError('Монитор отключён')
            chosen=None; i=0
            while True:
                dm=mode_at(u,device,i)
                if dm is None: break
                i+=1
                if dm.display.orientation%2 != old.display.orientation%2:
                    dm.width,dm.height=dm.height,dm.width
                if dm.bpp==32 and not dm.flags&2 and f'{dm.width}x{dm.height}@{dm.hz}'==mode:
                    chosen=dm; break
            if chosen is None: raise ValueError('Режим больше не доступен; пересканируйте мониторы')
            chosen.display.position=old.display.position
            chosen.display.orientation=orientation
            if (old.display.orientation%2)!=(orientation%2):
                chosen.width,chosen.height=chosen.height,chosen.width
            chosen.fields=0x40000|0x80000|0x100000|0x400000|0x80|0x20
            code=u.ChangeDisplaySettingsExW(device,C.byref(chosen),None,2,None)
            if code!=0: raise RuntimeError(f'Драйвер отклонил режим (CDS_TEST: {code})')
            code=u.ChangeDisplaySettingsExW(device,C.byref(chosen),None,0,None)
            if code!=0: raise RuntimeError(f'Не удалось переключить экран: {code}')
            ident=uuid.uuid4().hex
            self.result=None
            self.pending={'id':ident,'device':device,'old':old,'new':chosen,'deadline':time.monotonic()+20}
            t=threading.Timer(20,self.resolve,args=(ident,False)); t.daemon=True; t.start()
            return ident
    @crash_guarded
    def apply_layout(self,rows):
        from .display_layout import apply
        with self.lock:
            if self.pending:raise ValueError('Сначала подтвердите предыдущий режим')
            saved=apply(user32(),rows,enumerate_displays());ident=uuid.uuid4().hex
            self.result=None;self.pending={'id':ident,'device':'desktop','layout':saved,'deadline':time.monotonic()+20}
            t=threading.Timer(20,self.resolve,args=(ident,False));t.daemon=True;t.start();return ident
    @crash_guarded
    def apply_advanced(self,kind,body):
        from .display_advanced import hdr_begin,topology_begin
        with self.lock:
            if self.pending:raise ValueError('Сначала подтвердите предыдущий режим')
            callback=hdr_begin(body.get('id'),body.get('enabled')) if kind=='hdr' else topology_begin(body.get('topology'))
            ident=uuid.uuid4().hex;self.result=None
            self.pending={'id':ident,'device':body.get('id','desktop'),'custom':callback,'deadline':time.monotonic()+20}
            t=threading.Timer(20,self.resolve,args=(ident,False));t.daemon=True;t.start();return ident
    def status(self):
        with self.lock:
            if not self.pending: return None
            return {k:v for k,v in self.pending.items() if k in ('id','device')} | {'seconds':max(0,int(self.pending['deadline']-time.monotonic()))}
    def resolve(self,ident,keep):
        with self.lock:
            p=self.pending
            if not p or p['id']!=ident: return False
            requested_keep=keep
            if keep and time.monotonic()>p['deadline']: keep=False
            if 'custom' in p:
                try:p['custom'](keep);code=0
                except Exception:code=-1
                if p.get('watchdog') and not p['watchdog'].finish(bool(keep and code==0)):code=-1
                if keep and code!=0:
                    try:p['custom'](False)
                    except Exception:pass
                self.result={'id':ident,'kept':bool(keep and code==0),'code':code};self.pending=None
                return self.result['kept'] if requested_keep else code==0
            u=user32()
            if 'layout' in p:
                from .display_layout import restore,commit
                try:
                    if keep:commit(u,p['layout'])
                    else:restore(u,p['layout']['saved'],registry=False)
                    code=0
                except Exception:code=-1
                if p.get('watchdog') and not p['watchdog'].finish(bool(keep and code==0)):code=-1
                if keep and code!=0:
                    try:restore(u,p['layout']['saved'],registry=True)
                    except Exception:pass
                self.result={'id':ident,'kept':bool(keep and code==0),'code':code};self.pending=None
                return self.result['kept'] if requested_keep else code==0
            code=u.ChangeDisplaySettingsExW(p['device'],C.byref(p['new'] if keep else p['old']),None,1 if keep else 0,None)
            if p.get('watchdog') and not p['watchdog'].finish(bool(keep and code==0)):code=-1
            if keep and code!=0:
                try:u.ChangeDisplaySettingsExW(p['device'],C.byref(p['old']),None,1,None)
                except Exception:pass
            self.result={'id':ident,'kept':bool(keep and code==0),'code':code}
            self.pending=None
            return self.result['kept'] if requested_keep else code==0
    def wait(self,ident):
        while True:
            with self.lock:
                if not self.pending or self.pending['id']!=ident:
                    return bool(self.result and self.result['id']==ident and self.result['kept'])
            time.sleep(.15)
    def restore_pending(self):
        with self.lock:
            if self.pending: self.resolve(self.pending['id'],False)

INPUT_PARAMS={'key_delay':(0x16,0x17),'drag_windows':(0x26,0x25),'mouse_trails':(0x5e,0x5d),'mouse_speed':(0x70,0x71),'wheel_lines':(0x68,0x69),'key_repeat':(0x0A,0x0B),'wheel_horizontal':(0x6C,0x6D),'cursor_shadow':(0x101A,0x101B),'mouse_sonar':(0x101C,0x101D),'mouse_vanish':(0x1020,0x1021)}
NATIVE_KEYS=set(INPUT_PARAMS)|{'mouse_accel','mouse_swap','double_click'}
def read_input():
    u=user32(); result={}
    for key,(get,_) in INPUT_PARAMS.items():
        value=C.c_uint()
        if u.SystemParametersInfoW(get,0,C.byref(value),0): result[key]=str(value.value)
    result['mouse_swap']=str(int(bool(u.GetSystemMetrics(23))))
    result['double_click']=str(u.GetDoubleClickTime())
    values=(C.c_int*3)()
    if u.SystemParametersInfoW(3,0,values,0): result['mouse_accel']='on' if values[2] else 'off'
    return result

def set_input(key,value):
    u=user32()
    if key=='mouse_accel':
        arr=(C.c_int*3)(6,10,1) if value=='on' else (C.c_int*3)(0,0,0)
        ok=u.SystemParametersInfoW(4,0,arr,3)
    elif key=='mouse_swap':
        ok=u.SystemParametersInfoW(0x21,int(value),None,3)
    elif key=='double_click':
        ok=u.SystemParametersInfoW(0x20,int(value),None,3)
    elif key in ('cursor_shadow','mouse_sonar','mouse_vanish'):
        ok=u.SystemParametersInfoW(INPUT_PARAMS[key][1],0,C.c_void_p(int(value)),3)
    elif key=='mouse_speed':
        ok=u.SystemParametersInfoW(0x71,0,C.c_void_p(int(value)),3)
    else:
        ok=u.SystemParametersInfoW(INPUT_PARAMS[key][1],int(value),None,3)
    if not ok: raise C.WinError(C.get_last_error())


def get_mouse_params():
    arr=(C.c_int*3)()
    if not user32().SystemParametersInfoW(3,0,arr,0): raise C.WinError(C.get_last_error())
    return list(arr)

def set_mouse_params(values):
    if len(values)!=3 or any(type(v)!=int for v in values): raise ValueError('Invalid mouse parameters')
    arr=(C.c_int*3)(*values)
    if not user32().SystemParametersInfoW(4,0,arr,3): raise C.WinError(C.get_last_error())
