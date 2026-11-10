"""Start one allowlisted elevated action; the main UI stays unelevated."""
import ctypes as C
import hashlib
import json
import os
import queue
import secrets
import subprocess
import threading
import time


def request(backend,verb,value):
    from multiprocessing.connection import Listener
    from .admin_helper import validate_intent,encode,current_sid
    from .worker_process import worker_command
    intent=validate_intent({'verb':verb,'value':value});raw=encode(intent)
    name=r'\\.\pipe\KrolikAdmin-'+secrets.token_hex(24);key=secrets.token_bytes(32)
    listener=Listener(name,family='AF_PIPE',authkey=key);accepted=queue.Queue(maxsize=1)
    def accept():
        try:accepted.put(listener.accept())
        except Exception as exc:accepted.put(exc)
    threading.Thread(target=accept,daemon=True).start()
    command=worker_command('admin_helper',name,key.hex(),hashlib.sha256(raw).hexdigest(),current_sid(backend),str(os.getpid()))
    process_handle=None;connection=None
    try:
        from ctypes import wintypes as W
        class ExecuteInfo(C.Structure):
            _fields_=[('size',W.DWORD),('mask',W.ULONG),('hwnd',W.HWND),('verb',W.LPCWSTR),('file',W.LPCWSTR),('parameters',W.LPCWSTR),('directory',W.LPCWSTR),('show',C.c_int),('instance',W.HINSTANCE),('id_list',W.LPVOID),('class_name',W.LPCWSTR),('class_key',W.HKEY),('hotkey',W.DWORD),('icon',W.HANDLE),('process',W.HANDLE)]
        shell=C.WinDLL('shell32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
        shell.ShellExecuteExW.argtypes=[C.POINTER(ExecuteInfo)];shell.ShellExecuteExW.restype=W.BOOL
        kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
        kernel.CloseHandle.argtypes=[W.HANDLE]
        info=ExecuteInfo();info.size=C.sizeof(info);info.mask=0x40|0x100;info.verb='runas';info.file=command[0];info.parameters=subprocess.list2cmdline(command[1:]);info.show=0
        backend.progress('Подтвердите действие в окне Windows')
        if not shell.ShellExecuteExW(C.byref(info)):
            if C.get_last_error()==1223:raise ValueError('Действие отменено в окне Windows. Настройки не менялись.')
            raise ValueError('Не удалось запустить помощник администратора')
        process_handle=info.process;deadline=time.monotonic()+30
        while True:
            try:connection=accepted.get(timeout=.2);break
            except queue.Empty:
                if time.monotonic()>deadline or kernel.WaitForSingleObject(process_handle,0)==0:raise ValueError('Помощник не подключился. Проверьте выбранный аккаунт Windows.')
        if isinstance(connection,Exception):raise ValueError('Не удалось открыть канал помощника')
        connection.send_bytes(raw);backend.progress('Windows выполняет подтверждённое действие')
        deadline=time.monotonic()+7200
        while not connection.poll(.25):
            if kernel.WaitForSingleObject(process_handle,0)==0:raise ValueError('Помощник завершился без результата. Проверьте состояние Windows перед повтором.')
            if time.monotonic()>deadline:raise ValueError('Windows ещё не сообщила результат. Не повторяйте действие до проверки состояния.')
        reply=json.loads(connection.recv_bytes(65536))
        if not isinstance(reply,dict) or type(reply.get('ok'))!=bool:raise ValueError('Помощник вернул неверный ответ')
        if not reply['ok']:raise ValueError(str(reply.get('error','Не удалось выполнить действие'))[:2000])
        return reply.get('result')
    finally:
        if connection is not None and not isinstance(connection,Exception):connection.close()
        listener.close()
        if process_handle:kernel.CloseHandle(process_handle)
