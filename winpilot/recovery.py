"""Validate persisted undo data before it can reach OS APIs."""
import ipaddress
import re
from .windows import REG
from .workspace import GUID


def checked_undo(entries):
    if not isinstance(entries,list) or len(entries)>2000:raise ValueError('Повреждена резервная копия')
    def text(v,limit=1024):return isinstance(v,str) and 0<len(v)<=limit
    def integer(v,low,high):return type(v)==int and low<=v<=high
    allowed={(p,n) for items in REG.values() for p,n,_ in items}
    for v in entries:
        if not isinstance(v,dict):raise ValueError('Неверная запись отката')
        k=v.get('kind');x=v.get('value');valid=False
        if k=='registry':
            values=v.get('values');valid=isinstance(values,list) and len(values)<=20
            if valid:
                for r in values:
                    if not isinstance(r,dict) or (r.get('path'),r.get('name')) not in allowed or type(r.get('exists'))!=bool:valid=False;break
                    if r['exists']:
                        t=r.get('kind');data=r.get('value')
                        if not ((t in (1,2) and isinstance(data,str) and len(data)<=4096) or (t==4 and integer(data,0,2**32-1)) or (t==11 and integer(data,0,2**64-1))):valid=False;break
        elif k=='setting':
            key=v.get('key');ranges={'mouse_speed':(1,20),'wheel_lines':(0,2**32-1),'key_repeat':(0,31),'key_delay':(0,3),'drag_windows':(0,1),'mouse_trails':(0,20),'mouse_swap':(0,1),'double_click':(1,5000),'wheel_horizontal':(0,2**32-1),'cursor_shadow':(0,1),'mouse_sonar':(0,1),'mouse_vanish':(0,1)}
            valid=key=='power_plan' and text(x) and bool(GUID.fullmatch(x))
            if key=='time_zone':valid=text(x,150) and bool(re.fullmatch(r'[A-Za-z0-9 .()+_-]+',x))
            if key in ranges:valid=isinstance(x,str) and x.isdigit() and ranges[key][0]<=int(x)<=ranges[key][1]
        elif k=='power_seconds':
            if v.get('scheme') is not None and (not isinstance(v['scheme'],str) or not GUID.fullmatch(v['scheme'])):raise ValueError('Некорректная схема питания')
            valid=v.get('key') in ['screen_ac','screen_dc','sleep_ac','sleep_dc'] and isinstance(x,str) and x.isdigit() and 0<=int(x)<2**32
        elif k=='mouse_params':valid=isinstance(x,list) and len(x)==3 and all(integer(i,0,100) for i in x)
        elif k=='startup':valid=isinstance(v.get('key'),str) and bool(re.fullmatch(r'[a-f0-9]{64}',v['key'])) and type(x)==bool
        elif k=='brightness':valid=text(v.get('key')) and integer(x,0,100)
        elif k=='audio':valid=text(v.get('key')) and isinstance(x,dict) and type(x.get('mute'))==bool and type(x.get('scalar')) in (int,float) and 0<=x['scalar']<=1
        elif k=='audio_default':valid=text(v.get('key')) and text(x) and integer(v.get('flow'),0,1) and integer(v.get('role'),0,2)
        elif k=='dns':
            valid=integer(v.get('adapter'),1,2**31-1) and isinstance(x,dict) and type(x.get('auto'))==bool and isinstance(x.get('servers'),list) and len(x['servers'])<=16 and isinstance(x.get('guid',''),str) and (not x.get('guid') or bool(GUID.fullmatch(x['guid'].strip('{}'))))
            if valid:
                try:
                    for ip in x['servers']:ipaddress.IPv4Address(ip)
                except Exception:valid=False
        elif k=='languages':
            valid=isinstance(x,dict) and isinstance(x.get('languages'),list) and 1<=len(x['languages'])<=32
            if valid:
                for lang in x['languages']:
                    if not isinstance(lang,dict) or not isinstance(lang.get('LanguageTag'),str) or not re.fullmatch(r'[A-Za-z0-9-]{2,80}',lang['LanguageTag']) or not isinstance(lang.get('InputMethodTips'),list) or len(lang['InputMethodTips'])>32 or any(not text(t,200) for t in lang['InputMethodTips']):valid=False;break
                if x.get('tip') is not None and not isinstance(x['tip'],str):valid=False
        if not valid:raise ValueError('Недопустимая запись отката: '+str(k))
    return entries
