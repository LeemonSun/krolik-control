"""User logon/boot tasks, guarded by an immutable XML fingerprint and exact undo."""
import copy,hashlib,json,re,secrets,threading,time
from pathlib import Path
from .workspace import atomic_json

SCAN_PS=r'''$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;@(Get-ScheduledTask -ErrorAction Stop|Where-Object {$_.TaskPath -notlike '\Microsoft\*' -and ($_.Triggers|Where-Object {$_.CimClass.CimClassName -in @('MSFT_TaskLogonTrigger','MSFT_TaskBootTrigger')})}|Select-Object -First 200|ForEach-Object{$t=$_;$owner='';try{$account=[string]$t.Principal.UserId;if($account -like 'S-1-*'){$owner=$account}else{$owner=([Security.Principal.NTAccount]$account).Translate([Security.Principal.SecurityIdentifier]).Value}}catch{};$xml=Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop;$hash=[Security.Cryptography.SHA256]::Create();try{$sha=[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($xml))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()};@{name=$t.TaskName;path=$t.TaskPath;enabled=($t.State -ne 'Disabled');principal=$t.Principal.UserId;controllable=($owner -eq $sid);xml_sha256=$sha;commands=@($t.Actions|ForEach-Object {$_.Execute})}})|ConvertTo-Json -Depth 5 -Compress'''
APPLY_PS=r'''$t=Get-ScheduledTask -TaskPath $p.path -TaskName $p.name -ErrorAction Stop;$xml=Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop;$hash=[Security.Cryptography.SHA256]::Create();try{$sha=[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($xml))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()};if($sha -ne $p.expected){throw 'Задача изменилась после подтверждения'};if($p.enabled){$null=Enable-ScheduledTask -TaskPath $p.path -TaskName $p.name -ErrorAction Stop}else{$null=Disable-ScheduledTask -TaskPath $p.path -TaskName $p.name -ErrorAction Stop}'''

def digest(row):return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
class StartupTasks:
 def __init__(self,app,directory):self.app=app;self.path=Path(directory)/('startup-task-demo.json' if app.demo else 'startup-task.json');self.rows=[];self.previews={};self.lock=threading.RLock()
 def read(self):
  if self.app.demo:return copy.deepcopy(self.rows or [{'id':'demo-task','name':'Updater · пример','path':'\\KrolikDemo\\','enabled':True,'principal':'Текущий пользователь','controllable':True,'xml_sha256':'a'*64,'commands':['Updater.exe']}])
  result=self.app.backend.psjson(SCAN_PS,timeout=30);rows=result if isinstance(result,list) else [result] if isinstance(result,dict) else []
  for r in rows:r['id']=hashlib.sha256((r['path']+'\0'+r['name']).encode()).hexdigest()
  return rows
 def scan(self):
  rows=self.read()
  with self.lock:self.rows=copy.deepcopy(rows)
  return {'items':rows,'can_undo':self.can_undo(rows),'demo':self.app.demo}
 def can_undo(self,rows):
  saved=self.saved()
  return bool(saved and any(r.get('id')==saved['before']['id'] and r.get('controllable') is True and digest(r)==saved['after_digest'] for r in rows))
 def saved(self):
  try:
   if self.path.stat().st_size>65536:return None
   s=json.loads(self.path.read_text(encoding='utf-8'))
   if not isinstance(s,dict) or s.get('state')!='confirmed':return None
   before=s['before'];sha=s['after_digest']
   if not isinstance(before,dict) or not isinstance(before.get('id'),str) or type(before.get('enabled'))!=bool or before.get('controllable') is not True or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha):return None
   return s
  except (OSError,KeyError,ValueError,TypeError,AttributeError,RecursionError):return None
 def preview(self,body):
  if type(body.get('enabled'))!=bool:raise ValueError('Выберите включение или отключение')
  r=next((r for r in self.rows if r['id']==body.get('id')),None)
  if not r or not r.get('controllable'):raise ValueError('Доступно управление только задачами текущего пользователя; обновите список')
  if r['enabled']==body['enabled']:raise ValueError('Уже выбрано это состояние')
  token=secrets.token_urlsafe(24)
  with self.lock:self.previews={token:{'row':copy.deepcopy(r),'enabled':body['enabled'],'expires':time.monotonic()+90}}
  return {'token':token,'name':r['name'],'enabled':body['enabled'],'commands':r.get('commands',[])}
 def set(self,row,enabled):
  if self.app.demo:
   for r in self.rows:
    if r['id']==row['id']:r['enabled']=enabled;r['xml_sha256']=('b' if not enabled else 'a')*64
  else:self.app.backend.ps(APPLY_PS,{'path':row['path'],'name':row['name'],'enabled':enabled,'expected':row['xml_sha256']},timeout=30)
  rows=self.read();r=next((r for r in rows if r['id']==row['id']),None)
  if not r or r['enabled']!=enabled:raise ValueError('Windows не подтвердила состояние задачи')
  return r
 def apply(self,body):
  if body.get('confirmed') is not True:raise ValueError('Подтвердите изменение задачи автозапуска')
  with self.lock:job=self.previews.pop(body.get('token'),None) if isinstance(body.get('token'),str) else None
  if not job or time.monotonic()>job['expires']:raise ValueError('Подтверждение устарело')
  row=job['row'];live=next((r for r in self.read() if r['id']==row['id']),None)
  if not live or digest(live)!=digest(row) or not live.get('controllable'):raise ValueError('Задача изменилась. Обновите список.')
  saved={'before':row,'after':job['enabled'],'state':'prepared'};atomic_json(self.path,saved)
  after=self.set(row,job['enabled']);saved.update(after_digest=digest(after),state='confirmed');atomic_json(self.path,saved)
  return {'message':'Состояние задачи подтверждено. Изменение действует при следующем запуске её триггера.','verification':'confirmed',**self.scan()}
 def undo(self,body):
  if body.get('confirmed') is not True:raise ValueError('Подтвердите возврат автозапуска задачи')
  saved=self.saved();rows=self.read();current=next((r for r in rows if saved and r.get('id')==saved['before']['id'] and r.get('controllable') is True and digest(r)==saved['after_digest']),None)
  if not current:raise ValueError('Задача изменилась или последнего изменения нет')
  self.set(current,saved['before']['enabled']);saved['state']='returned';atomic_json(self.path,saved)
  return {'message':'Прежнее состояние задачи возвращено','verification':'confirmed',**self.scan()}
