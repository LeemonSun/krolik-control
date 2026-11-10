"""Windows tray and opt-in shortcuts. Selecting a profile only opens its preview."""
import ctypes as C
from ctypes import wintypes as W
import threading


class DesktopBridge:
    def __init__(self,app,open_window):
        self.app=app;self.open_window=open_window;self.active=False;self.hwnd=None
        self.state={'available':False,'hotkeys':False,'conflicts':[]}
        self.stop_event=threading.Event();self.window_tag=app.window_tag

    def start(self):
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()

    def snapshot(self):
        return {**self.state,'conflicts':list(self.state['conflicts'])}

    def focus(self,hide=False):
        u=C.WinDLL('user32',use_last_error=True)
        callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
        u.ShowWindow.argtypes=[W.HWND,C.c_int];u.SetForegroundWindow.argtypes=[W.HWND]
        found=[]
        def visit(hwnd,param):
            title=C.create_unicode_buffer(512);u.GetWindowTextW(hwnd,title,512)
            if title.value.startswith('Krolik Control') and title.value.endswith(self.window_tag):
                u.ShowWindow(hwnd,0 if hide else 9)
                if not hide:u.SetForegroundWindow(hwnd)
                found.append(hwnd);return False
            return True
        cb=callback(visit);u.EnumWindows.argtypes=[callback,W.LPARAM];u.EnumWindows(cb,0)
        if not found and not hide:self.open_window()
        return bool(found)

    def select(self,name=None):
        with self.app.lock:
            if self.app.engine.snapshot()['running'] or self.app.mutation_running():return
            if name is not None and not any(p['name']==name for p in self.app.workspace.value['profiles']):return
            self.app.desktop_sequence+=1
            self.app.data['desktop_action']={'sequence':self.app.desktop_sequence,'profile':name}
            self.app.data_revision+=1
        self.focus()

    def close(self):
        self.stop_event.set()
        if self.hwnd:
            u=C.WinDLL('user32',use_last_error=True);u.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
            u.PostMessageW(self.hwnd,0x0010,0,0)

    def _run(self):
        try:self._message_loop()
        except Exception:
            self.state={'available':False,'hotkeys':False,'conflicts':['Не удалось включить меню в трее']}
        finally:self.active=False

    def _message_loop(self):
        u=C.WinDLL('user32',use_last_error=True);s=C.WinDLL('shell32',use_last_error=True);k=C.WinDLL('kernel32',use_last_error=True)
        proc_type=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        class WindowClass(C.Structure):
            _fields_=[('style',W.UINT),('proc',proc_type),('extra1',C.c_int),('extra2',C.c_int),('instance',W.HINSTANCE),('icon',W.HICON),('cursor',W.HANDLE),('background',W.HBRUSH),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
        class Notify(C.Structure):
            _fields_=[('size',W.DWORD),('hwnd',W.HWND),('ident',W.UINT),('flags',W.UINT),('message',W.UINT),('icon',W.HICON),('tip',W.WCHAR*128),('state',W.DWORD),('mask',W.DWORD),('info',W.WCHAR*256),('timeout',W.UINT),('title',W.WCHAR*64),('info_flags',W.DWORD),('guid',C.c_byte*16),('balloon',W.HICON)]
        k.GetModuleHandleW.argtypes=[W.LPCWSTR];k.GetModuleHandleW.restype=W.HMODULE
        u.DefWindowProcW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];u.DefWindowProcW.restype=C.c_ssize_t
        u.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,W.LPVOID];u.CreateWindowExW.restype=W.HWND
        u.RegisterClassW.argtypes=[C.POINTER(WindowClass)];u.RegisterClassW.restype=W.ATOM
        u.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,C.c_int,C.c_int,W.UINT];u.LoadImageW.restype=W.HANDLE
        u.LoadIconW.argtypes=[W.HINSTANCE,C.c_void_p];u.LoadIconW.restype=W.HICON
        u.CreatePopupMenu.restype=W.HMENU;u.AppendMenuW.argtypes=[W.HMENU,W.UINT,C.c_size_t,W.LPCWSTR]
        u.TrackPopupMenu.argtypes=[W.HMENU,W.UINT,C.c_int,C.c_int,C.c_int,W.HWND,W.LPVOID];u.TrackPopupMenu.restype=W.UINT
        u.DestroyMenu.argtypes=[W.HMENU];u.SetForegroundWindow.argtypes=[W.HWND]
        u.RegisterHotKey.argtypes=[W.HWND,C.c_int,W.UINT,W.UINT];u.UnregisterHotKey.argtypes=[W.HWND,C.c_int]
        u.SetTimer.argtypes=[W.HWND,C.c_size_t,W.UINT,C.c_void_p];u.KillTimer.argtypes=[W.HWND,C.c_size_t]
        u.DestroyWindow.argtypes=[W.HWND];u.DestroyIcon.argtypes=[W.HICON]
        u.RegisterWindowMessageW.argtypes=[W.LPCWSTR];u.RegisterWindowMessageW.restype=W.UINT
        u.UnregisterClassW.argtypes=[W.LPCWSTR,W.HINSTANCE]
        s.Shell_NotifyIconW.argtypes=[W.DWORD,C.POINTER(Notify)]
        registered={};last_config=None
        def keys():
            nonlocal last_config
            enabled=self.app.workspace.value.get('ui',{}).get('quick_keys',False)
            names=tuple(p['name'] for p in self.app.workspace.value['profiles'][:9]);config=(enabled,names)
            if config==last_config:return
            for ident in registered:u.UnregisterHotKey(self.hwnd,ident)
            registered.clear();conflicts=[]
            if enabled:
                for i,name in enumerate(names):
                    ident=100+i
                    if u.RegisterHotKey(self.hwnd,ident,0x4003,ord('1')+i):registered[ident]=name
                    else:conflicts.append('Ctrl+Alt+'+str(i+1))
            self.state={'available':True,'hotkeys':enabled,'conflicts':conflicts};last_config=config
            with self.app.lock:self.app.data_revision+=1
        def menu():
            handle=u.CreatePopupMenu()
            try:
                u.AppendMenuW(handle,0,1,'Открыть Krolik Control')
                names=[p['name'] for p in self.app.workspace.value['profiles'][:20]]
                if names:u.AppendMenuW(handle,0x800,0,None)
                for i,name in enumerate(names):u.AppendMenuW(handle,0,100+i,name.replace('&','&&'))
                u.AppendMenuW(handle,0x800,0,None);u.AppendMenuW(handle,0,2,'Выход')
                point=W.POINT();u.GetCursorPos(C.byref(point));u.SetForegroundWindow(self.hwnd)
                chosen=u.TrackPopupMenu(handle,0x100|0x2,point.x,point.y,0,self.hwnd,None)
                if chosen==1:self.select()
                elif chosen==2:
                    if self.app.engine.snapshot()['running'] or self.app.mutation_running():self.select()
                    else:
                        self.app.close_requested=True
                        if self.app.http:threading.Thread(target=self.app.http.shutdown,daemon=True).start()
                elif 100<=chosen<100+len(names):self.select(names[chosen-100])
            finally:u.DestroyMenu(handle)
        taskbar=u.RegisterWindowMessageW('TaskbarCreated')
        def window_proc(hwnd,msg,wp,lp):
            try:
                if msg==0x8001:
                    if lp==0x0203:self.select()
                    elif lp in (0x0205,0x007B):menu()
                    return 0
                if msg==0x0113:keys();return 0
                if msg==0x0312:
                    if wp in registered:self.select(registered[wp])
                    return 0
                if msg==taskbar:s.Shell_NotifyIconW(0,C.byref(notification));return 0
                if msg==0x0010:u.DestroyWindow(hwnd);return 0
                if msg==0x0002:u.PostQuitMessage(0);return 0
            except Exception:pass
            return u.DefWindowProcW(hwnd,msg,wp,lp)
        callback=proc_type(window_proc);instance=k.GetModuleHandleW(None);name='KrolikTray_'+self.window_tag
        wc=WindowClass();wc.proc=callback;wc.instance=instance;wc.name=name
        if not u.RegisterClassW(C.byref(wc)):raise C.WinError(C.get_last_error())
        icon=None
        try:
            self.hwnd=u.CreateWindowExW(0,name,name,0,0,0,0,0,None,None,instance,None)
            if not self.hwnd:raise C.WinError(C.get_last_error())
            icon=u.LoadImageW(None,str(self.app.ui/'favicon.ico'),1,32,32,0x10)
            notification=Notify();notification.size=C.sizeof(Notify);notification.hwnd=self.hwnd;notification.ident=1;notification.flags=0x7;notification.message=0x8001;notification.icon=icon or u.LoadIconW(None,C.c_void_p(32512));notification.tip='Krolik Control'
            if not s.Shell_NotifyIconW(0,C.byref(notification)):raise RuntimeError('Tray unavailable')
            self.active=True;keys();u.SetTimer(self.hwnd,1,1500,None)
            message=W.MSG()
            while u.GetMessageW(C.byref(message),None,0,0)>0:
                u.TranslateMessage(C.byref(message));u.DispatchMessageW(C.byref(message))
        finally:
            if self.hwnd:
                u.KillTimer(self.hwnd,1)
                for ident in registered:u.UnregisterHotKey(self.hwnd,ident)
                if 'notification' in locals():s.Shell_NotifyIconW(2,C.byref(notification))
            if icon:u.DestroyIcon(icon)
            u.UnregisterClassW(name,instance);self.hwnd=None
