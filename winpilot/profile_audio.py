"""Default audio roles used by plans. No change without a known previous device."""
def default_id(rows,flow,role):
    return next((r['id'] for r in rows if r.get('flow')==flow and
                 role in r.get('default_roles',([1] if r.get('default') else []))),None)

def read_default(flow,role):
    from .audio import enumerate_audio
    ident=default_id(enumerate_audio(),flow,role)
    if not ident:raise ValueError('Windows не сообщила прежнее устройство звука. Переключение отменено.')
    return ident

def set_role(ident,flow,role):
    from .audio import enumerate_audio
    from .audio_routing import set_default
    if not any(r['id']==ident and r['flow']==flow for r in enumerate_audio()):
        raise ValueError('Аудиоустройство отключено. Подключите его и повторите.')
    set_default(ident,role)

def validate_defaults(plan,info,demo=False):
    rows=plan.get('audio_defaults',[])
    if type(plan.get('audio_routing_ack',False))!=bool:raise ValueError('Некорректное подтверждение звука')
    if not isinstance(rows,list) or len(rows)>6:raise ValueError('Некорректный выбор основного звука')
    if rows and not plan.get('audio_routing_ack'):raise ValueError('Подтвердите пробный режим переключения звука')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'id','flow','role'} or not isinstance(row['id'],str) or not 1<=len(row['id'])<=1024 or type(row['flow'])!=int or row['flow'] not in (0,1) or type(row['role'])!=int or row['role'] not in (0,1,2):
            raise ValueError('Некорректная роль аудиоустройства')
        pair=(row['flow'],row['role'])
        if pair in seen:raise ValueError('Для одной роли выбрано несколько аудиоустройств')
        seen.add(pair)
        if not any(r['id']==row['id'] and r['flow']==row['flow'] for r in info.get('endpoints',[])):
            raise ValueError('Аудиоустройство профиля отключено')
