"""Per-session audio controls with exact readback and persistent single-step undo."""
import copy,json,secrets,threading,time
from pathlib import Path
from .workspace import atomic_json

def checked(body):
 if not isinstance(body.get('id'),str) or not 1<=len(body['id'])<=4096 or type(body.get('volume'))!=int or not 0<=body['volume']<=100 or type(body.get('mute'))!=bool:raise ValueError('Выберите сессию, громкость 0–100 и состояние звука')
 return {k:body[k] for k in ('id','volume','mute')}
def same(a,b):return bool(a and b and all(a.get(k)==b.get(k) for k in ('id','volume','mute')))
class Mixer:
 def __init__(self,app,directory):self.app=app;self.path=Path(directory)/('mixer-demo.json' if app.demo else 'mixer.json');self.rows=[];self.previews={};self.lock=threading.RLock()
 def read(self):
  if self.app.demo:return copy.deepcopy(self.rows or [{'id':'demo-session','name':'Браузер · пример','pid':4243,'volume':65,'mute':False,'active':True}])
  from .audio import audio_sessions
  return audio_sessions()
 def scan(self):
  result=self.read()
  with self.lock:self.rows=result
  return {'items':result,'can_undo':self.status(result),'demo':self.app.demo}
 def status(self,rows):
  saved=self.saved()
  return bool(saved and any(same(r,saved['after']) for r in rows))
 def saved(self):
  try:
   if self.path.stat().st_size>32768:return None
   s=json.loads(self.path.read_text(encoding='utf-8'))
   if not isinstance(s,dict) or s.get('state')!='confirmed':return None
   before=checked(s['before']);after=checked(s['after'])
   return {**s,'before':before,'after':after} if before['id']==after['id'] else None
  except (OSError,ValueError,KeyError,TypeError,AttributeError,RecursionError):return None
 def preview(self,body):
  value=checked(body);current=next((r for r in self.read() if r['id']==value['id']),None)
  if not current:raise ValueError('Аудиосессия закрылась; обновите микшер')
  token=secrets.token_urlsafe(24)
  with self.lock:self.previews={token:{'before':current,'after':value,'expires':time.monotonic()+60}}
  return {'token':token,'name':current['name']}
 def set(self,row):
  if self.app.demo:
   rows=self.read()
   for r in rows:
    if r['id']==row['id']:r.update(volume=row['volume'],mute=row['mute'])
   self.rows=rows
  else:
   from .audio import set_session
   set_session(row['id'],row['mute'],row['volume'])
  if not any(same(r,row) for r in self.read()):raise ValueError('Windows не подтвердила громкость сессии')
 def apply(self,body):
  with self.lock:
   job=self.previews.pop(body.get('token'),None) if isinstance(body.get('token'),str) else None
   if not job or time.monotonic()>job['expires']:raise ValueError('Выбор устарел. Повторите применение.')
  current=next((r for r in self.read() if r['id']==job['before']['id']),None)
  if not same(current,job['before']):raise ValueError('Громкость изменилась в другом приложении; обновите микшер')
  saved={'version':1,'before':checked(job['before']),'after':job['after'],'state':'prepared'};atomic_json(self.path,saved)
  try:self.set(job['after']);saved['state']='confirmed';atomic_json(self.path,saved)
  except Exception:
   try:self.set(job['before']);saved['state']='returned'
   except Exception:saved['state']='uncertain'
   atomic_json(self.path,saved);raise
  return {'verification':'confirmed','operation':saved['after'],'message':'Громкость сессии подтверждена' if not self.app.demo else 'Пример: громкость системы не менялась',**self.scan()}
 def undo(self,body):
  if body.get('confirmed') is not True:raise ValueError('Подтвердите возврат громкости')
  saved=self.saved();rows=self.read()
  if not saved or not any(same(r,saved['after']) for r in rows):raise ValueError('Возврат недоступен: сессия закрылась или её настройки изменились')
  self.set(saved['before']);saved['state']='returned';atomic_json(self.path,saved)
  return {'verification':'confirmed','message':'Прежняя громкость сессии возвращена',**self.scan()}
