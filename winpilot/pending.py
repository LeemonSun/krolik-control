"""Durable readback queue; persisted data can request reads, never command replay."""
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
from .workspace import atomic_json
KINDS={'setting','audio','audio_default','brightness','startup','app','upgrade','languages','layout','display','update','package_manager','driver_safety','restore_point'}
def fingerprint(op):
    return hashlib.sha256(json.dumps({k:op.get(k) for k in ('kind','key','value','orientation','adapter')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def checked(op):
    if not isinstance(op,dict) or op.get('kind') not in KINDS or not isinstance(op.get('key'),str) or len(op['key'])>2048 or 'value' not in op:raise ValueError('Неверное действие проверки')
    if len(json.dumps(op,ensure_ascii=False))>40000:raise ValueError('Слишком большое действие')
    return copy.deepcopy(op)
class PendingChecks:
    def __init__(self,directory):
        self.path=Path(directory)/'pending-checks.json';self.lock=threading.RLock();self.rows=[];self.warning=''
        try:
            if self.path.exists():
                if self.path.stat().st_size>4*1024**2:raise ValueError()
                rows=json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(rows,list) or len(rows)>100:raise ValueError()
                for r in rows:
                    checked(r['operation'])
                    if r['id']!=fingerprint(r['operation']) or r['status'] not in ('unverified','deferred') or not isinstance(r.get('message'),str):raise ValueError()
                self.rows=rows
        except (ValueError,OSError,KeyError,TypeError,RecursionError,UnicodeError):self.warning='Не удалось прочитать ожидающие проверки; автоматического повтора нет.'
    def snapshot(self):
        with self.lock:return copy.deepcopy(self.rows)
    def contains(self,op):
        with self.lock:return any(r['id']==fingerprint(op) for r in self.rows)
    def require_capacity(self,ops):
        with self.lock:
            if len({r['id'] for r in self.rows}|{fingerprint(op) for op in ops})>100:raise ValueError('Слишком много действий могут ожидать проверки. Сначала проверьте предыдущие результаты или уменьшите очередь.')
    def add(self,op,status,message):
        if status not in ('unverified','deferred'):raise ValueError('Неизвестное ожидание проверки')
        op=checked(op)
        with self.lock:
            rows=[r for r in self.rows if r['id']!=fingerprint(op)]
            if len(rows)>=100:raise ValueError('Слишком много действий ожидают проверки')
            rows.append({'id':fingerprint(op),'created':time.time(),'operation':op,'status':status,'message':str(message)[:2000]});atomic_json(self.path,rows);self.rows=rows
    def remove(self,ident):
        with self.lock:
            rows=[r for r in self.rows if r['id']!=ident]
            if len(rows)==len(self.rows):raise ValueError('Проверка уже закрыта')
            atomic_json(self.path,rows);self.rows=rows
