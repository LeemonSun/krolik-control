"""Opt-in default-device bridge. PolicyConfig is undocumented; readback is mandatory.
No interface guessing or fallback vtable calls. Explicitly experimental until
the declared Windows matrix is exercised on real machines.
"""
import ctypes as C
import json
from pathlib import Path
import time
from .workspace import atomic_json

ROLES={0:'Системные звуки',1:'Музыка и приложения',2:'Связь'}

def set_default(ident,role):
    from .audio import enumerator,guid,call,release,check,enumerate_audio
    rows=enumerate_audio();row=next((r for r in rows if r['id']==ident),None)
    if not row or type(role)!=int or role not in ROLES:raise ValueError('Устройство или роль недоступны')
    with enumerator() as (_,ole):
        ptr=C.c_void_p();cls=guid('870af99c-171d-4f9e-af0d-e63df40c2bc9');iid=guid('f8679f50-850a-41cf-9c72-430f290290c8')
        try:
            check(ole.CoCreateInstance(C.byref(cls),None,1,C.byref(iid),C.byref(ptr)))
            check(call(ptr,13,[C.c_wchar_p,C.c_int],ident,role))
        finally:release(ptr)
    actual=enumerate_audio()
    if not any(r['id']==ident and role in r.get('default_roles',[]) for r in actual):raise ValueError('Windows не подтвердила смену основного устройства')
    return actual

class AudioRouter:
    def __init__(self,app,directory):self.app=app;self.path=Path(directory)/('audio-routing-demo.json' if app.demo else 'audio-routing.json')
    def status(self):
        try:
            if self.path.stat().st_size>16384:return {'previous_available':False}
            saved=json.loads(self.path.read_text(encoding='utf-8'))
            if saved.get('state')!='confirmed' or not saved.get('before') or type(saved.get('role'))!=int or saved['role'] not in ROLES:return {'previous_available':False}
            rows=(self.app.info or {}).get('endpoints',[])
            current=next((r for r in rows if r['flow']==saved['flow'] and saved['role'] in r.get('default_roles',([1] if r.get('default') else []))),None)
            previous=any(r['id']==saved['before'] and r['flow']==saved['flow'] for r in rows)
            return {'previous_available':bool(current and current['id']==saved['after'] and previous),'role':saved['role']}
        except (OSError,ValueError,KeyError,TypeError,AttributeError):return {'previous_available':False}
    def apply(self,body):
        role=body.get('role');ident=body.get('id')
        if body.get('confirmed') is not True or body.get('experimental_ack') is not True:raise ValueError('Подтвердите экспериментальное переключение устройства')
        if type(role)!=int or role not in ROLES or not isinstance(ident,str):raise ValueError('Неизвестная роль звука')
        if self.app.demo:rows=self.app.info.get('endpoints',[])
        else:
            from .audio import enumerate_audio
            rows=enumerate_audio()
        target=next((r for r in rows if r['id']==ident),None)
        if not target:raise ValueError('Устройство отключено')
        old=next((r['id'] for r in rows if r['flow']==target['flow'] and role in r.get('default_roles',([1] if r.get('default') else []))),None)
        if old==ident:return {'verification':'confirmed','message':'Это устройство уже выбрано для роли'}
        saved={'version':1,'role':role,'before':old,'after':ident,'flow':target['flow'],'time':time.time(),'state':'prepared'}
        atomic_json(self.path,saved)
        if self.app.demo:
            for r in rows:
                if r['flow']!=target['flow']:continue
                roles=set(r.get('default_roles',([1] if r.get('default') else [])));roles.discard(role)
                if r['id']==ident:roles.add(role)
                r['default_roles']=sorted(roles);r['default']=1 in roles
        else:
            try:rows=set_default(ident,role)
            except Exception:
                saved['state']='uncertain';atomic_json(self.path,saved)
                if old:
                    try:set_default(old,role);saved['state']='returned';atomic_json(self.path,saved)
                    except Exception:pass
                raise ValueError('Переключение не подтверждено. Проверьте основной выход звука.') from None
        saved['state']='confirmed';atomic_json(self.path,saved)
        with self.app.lock:
            self.app.info['endpoints']=rows
            if self.app.demo and hasattr(self.app.backend,'info'):self.app.backend.info['endpoints']=rows
            self.app.data_revision+=1
        return {'verification':'confirmed','message':'Устройство выбрано для роли «'+ROLES[role]+'»','previous_available':bool(old)}

    def undo(self,body):
        if body.get('confirmed') is not True or body.get('experimental_ack') is not True:raise ValueError('Подтвердите возврат устройства')
        try:
            if self.path.stat().st_size>16384:raise ValueError()
            saved=json.loads(self.path.read_text(encoding='utf-8'))
            if saved.get('state')!='confirmed' or not saved.get('before') or type(saved.get('role'))!=int or saved['role'] not in ROLES:raise ValueError()
        except (OSError,ValueError,TypeError,AttributeError):raise ValueError('Нет подтверждённого переключения для возврата') from None
        if self.app.demo:rows=self.app.info.get('endpoints',[])
        else:
            from .audio import enumerate_audio
            rows=enumerate_audio()
        current=next((r for r in rows if r['flow']==saved['flow'] and saved['role'] in r.get('default_roles',([1] if r.get('default') else []))),None)
        previous=next((r for r in rows if r['id']==saved['before'] and r['flow']==saved['flow']),None)
        if not current or current['id']!=saved['after']:raise ValueError('Основное устройство уже изменилось. Возврат не выполнялся.')
        if not previous:raise ValueError('Предыдущее устройство отключено. Возврат не выполнялся.')
        self.apply({'id':saved['before'],'role':saved['role'],'confirmed':True,'experimental_ack':True})
        saved['state']='returned';atomic_json(self.path,saved)
        return {'verification':'confirmed','message':'Предыдущее устройство возвращено','previous_available':False}
