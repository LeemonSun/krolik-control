"""Documented ChangeDisplaySettingsEx transaction for active desktop positions."""
import copy
import ctypes as C


def validate_layout(rows,displays):
    if not isinstance(rows,list) or not 1<=len(rows)<=16:raise ValueError('Некорректная схема экранов')
    known={d['id']:d for d in displays}
    if len(rows)!=len(known):raise ValueError('Состав мониторов изменился; обновите список')
    seen=set();primary=[];rects={}
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'id','x','y','primary'} or not isinstance(r['id'],str) or r['id'] not in known or r['id'] in seen:raise ValueError('Неизвестный монитор в схеме')
        if any(type(r[k])!=int or not -32768<=r[k]<=32767 for k in ('x','y')) or type(r['primary'])!=bool:raise ValueError('Недопустимое положение монитора')
        seen.add(r['id'])
        if r['primary']:primary.append(r)
        w,h=map(int,known[r['id']]['current'].split('@')[0].split('x'));rects[r['id']]=(r['x'],r['y'],r['x']+w,r['y']+h)
    if len(primary)!=1 or primary[0]['x'] or primary[0]['y']:raise ValueError('Основной экран должен быть в точке 0, 0')
    connected={primary[0]['id']}
    for a,ra in rects.items():
        for b,rb in rects.items():
            if a!=b and min(ra[2],rb[2])>max(ra[0],rb[0]) and min(ra[3],rb[3])>max(ra[1],rb[1]):raise ValueError('Мониторы не должны перекрываться')
    while True:
        before=len(connected)
        for a,ra in rects.items():
            for b in list(connected):
                rb=rects[b]
                if ((ra[0]==rb[2] or ra[2]==rb[0]) and min(ra[3],rb[3])>max(ra[1],rb[1])) or ((ra[1]==rb[3] or ra[3]==rb[1]) and min(ra[2],rb[2])>max(ra[0],rb[0])):connected.add(a)
        if before==len(connected):break
    if len(connected)!=len(rows):raise ValueError('Каждый экран должен примыкать к другому')
    return copy.deepcopy(rows)


def snapshot(u,displays):
    from .native import mode_at
    rows=[]
    for d in displays:
        current=mode_at(u,d['id'],-1);stored=mode_at(u,d['id'],-2)
        if current is None or stored is None:raise ValueError('Не удалось сохранить исходную схему экранов')
        rows.append({'id':d['id'],'primary':d['primary'],'current':current,'stored':stored})
    return rows


def stage(u,rows,field):
    # All rows are staged before applying so primary changes remain one transaction.
    for r in sorted(rows,key=lambda x:not x['primary']):
        code=u.ChangeDisplaySettingsExW(r['id'],C.byref(r[field]),None,0x10000001|(0x10 if r['primary'] else 0),None)
        if code!=0:raise RuntimeError(f'Драйвер отклонил расположение экранов: {code}')


def live(u,rows,field):
    for r in sorted(rows,key=lambda x:not x['primary']):
        code=u.ChangeDisplaySettingsExW(r['id'],C.byref(r[field]),None,0x10 if r['primary'] else 0,None)
        if code!=0:raise RuntimeError(f'Не удалось переключить расположение: {code}')


def restore(u,rows,registry=True):
    errors=[]
    try:live(u,rows,'current')
    except Exception as exc:errors.append(str(exc))
    if registry:
        try:stage(u,rows,'stored')
        except Exception as exc:errors.append(str(exc))
    if errors:raise RuntimeError('Не удалось полностью вернуть схему экранов: '+'; '.join(errors))


def commit(u,transaction):
    try:
        stage(u,transaction['new'],'new')
        code=u.ChangeDisplaySettingsExW(None,None,None,0,None)
        if code!=0:raise RuntimeError(f'Не удалось сохранить схему: {code}')
    except Exception:
        restore(u,transaction['saved']);raise


def apply(u,rows,displays):
    rows=validate_layout(rows,displays);saved=snapshot(u,displays);changed=[]
    for r in rows:
        dm=type(saved[0]['current']).from_buffer_copy(next(v['current'] for v in saved if v['id']==r['id']))
        dm.display.position.x=r['x'];dm.display.position.y=r['y'];dm.fields|=0x20
        code=u.ChangeDisplaySettingsExW(r['id'],C.byref(dm),None,2,None)
        if code!=0:raise RuntimeError(f'Положение не поддерживается: {code}')
        changed.append({'id':r['id'],'primary':r['primary'],'new':dm})
    try:live(u,changed,'new')
    except Exception:
        restore(u,saved,registry=False);raise
    return {'saved':saved,'new':changed}
