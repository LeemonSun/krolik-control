"""One-operation UAC worker. JSON messages only; no arbitrary command or script verb."""
import hashlib
import ipaddress
import json
import re
import sys
import time

PIPE_PREFIX=r'\\.\pipe\KrolikAdmin-'


def validate_channel(name,key,digest,sid,parent):
    if not isinstance(name,str) or not re.fullmatch(re.escape(PIPE_PREFIX)+r'[a-f0-9]{48}',name) or not re.fullmatch(r'[a-f0-9]{64}',key) or not re.fullmatch(r'[a-f0-9]{64}',digest) or not re.fullmatch(r'S-1-(?:[0-9]+-)*[0-9]+',sid) or not re.fullmatch(r'[0-9]{1,10}',parent) or not 0<int(parent)<2**32:raise ValueError('Некорректный канал помощника')


def encode(value):
    return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('ascii')


def validate_intent(intent):
    if not isinstance(intent,dict) or set(intent)!={'verb','value'}:raise ValueError('Некорректное действие помощника')
    verb,value=intent['verb'],intent['value']
    if verb in ('restore_point','driver_backup','probe'):
        if value!={}:raise ValueError('Лишние параметры помощника')
    elif verb=='time_zone':
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9 .()+_-]{1,150}',value):raise ValueError('Неизвестный часовой пояс')
    elif verb=='dns':
        if not isinstance(value,dict) or set(value)!={'adapter','guid','choice'} or type(value['adapter'])!=int or not 1<=value['adapter']<2**31 or value['choice'] not in ('auto','google','cloudflare') or not isinstance(value['guid'],str) or not re.fullmatch(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}',value['guid']):raise ValueError('Некорректный сетевой адаптер')
    elif verb=='dns_restore':
        from .recovery import checked_undo
        checked_undo([value])
        if value.get('kind')!='dns' or not value['value'].get('guid'):raise ValueError('Не сохранён идентификатор адаптера')
    elif verb=='update':
        if not isinstance(value,dict) or set(value)!={'id','revision'} or not isinstance(value['id'],str) or not re.fullmatch(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}',value['id']) or type(value['revision'])!=int or not 1<=value['revision']<2**31:raise ValueError('Некорректное обновление Windows')
    else:raise ValueError('Действие не разрешено помощнику')
    if len(encode(intent))>16384:raise ValueError('Слишком большой запрос помощника')
    return intent


def current_sid(backend):
    match=re.search(r'S-1-(?:[0-9]+-)*[0-9]+',backend.run(['whoami.exe','/user','/fo','csv','/nh']))
    if not match:raise ValueError('Не удалось определить пользователя Windows')
    return match.group()


def execute(backend,intent):
    validate_intent(intent)
    if not backend.is_admin():raise ValueError('Помощнику не предоставлены права администратора')
    verb,value=intent['verb'],intent['value']
    if verb=='probe':return {'admin':True}
    if verb=='restore_point':return backend.restore_point()
    if verb=='driver_backup':
        from .driver_safety import create
        return create(backend)
    if verb=='update':return backend.install_update(value['id'],value['revision'])
    if verb=='time_zone':
        zones=backend.psjson('@(Get-TimeZone -ListAvailable | ForEach-Object {$_.Id}) | ConvertTo-Json -Compress')
        if value not in (zones or []):raise ValueError('Часовой пояс отсутствует в Windows')
        backend.apply_setting('time_zone',value);return None
    if verb=='dns':
        actual=backend.psjson('[string](Get-NetAdapter -InterfaceIndex $p.id -ErrorAction Stop).InterfaceGuid | ConvertTo-Json -Compress',{'id':value['adapter']})
        if str(actual).strip('{}').casefold()!=value['guid'].casefold():raise ValueError('Сетевой адаптер изменился. Повторите проверку.')
        backend.apply_setting('dns',value['choice'],value['adapter']);return None
    if verb=='dns_restore':return backend.restore_dns(value)


def main():
    from multiprocessing.connection import Client
    from .windows import Windows
    if len(sys.argv)!=6:raise ValueError('Неверный запуск помощника')
    _,name,key,digest,expected_sid,parent=sys.argv
    validate_channel(name,key,digest,expected_sid,parent)
    backend=Windows()
    if current_sid(backend)!=expected_sid:raise ValueError('Выбран другой аккаунт администратора. Действие отменено.')
    with Client(name,family='AF_PIPE',authkey=bytes.fromhex(key)) as connection:
        # Bind to the actual parent pipe server, not a process ID supplied in JSON.
        import ctypes as C
        from ctypes import wintypes as W
        kernel=C.WinDLL('kernel32',use_last_error=True);pid=W.ULONG()
        kernel.GetNamedPipeServerProcessId.argtypes=[W.HANDLE,C.POINTER(W.ULONG)]
        if not kernel.GetNamedPipeServerProcessId(connection.fileno(),C.byref(pid)) or pid.value!=int(parent):raise ValueError('Канал принадлежит другому процессу')
        if not connection.poll(20):return
        try:
            raw=connection.recv_bytes(16384)
            if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Запрос помощника изменился')
            intent=validate_intent(json.loads(raw))
            result=execute(backend,intent)
            reply={'ok':True,'result':result}
        except Exception as exc:reply={'ok':False,'error':str(exc)[:2000]}
        connection.send_bytes(encode(reply))


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit(1)
