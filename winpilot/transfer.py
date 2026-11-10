"""Explicit export of readable settings and a curated reinstall plan, never execution."""
import copy
from .catalog import BY_KEY,APPS
from .workspace import saved_plan

def snapshot(info,programs,backups):
 settings={}
 for key,value in info.get('settings',{}).items():
  if key not in BY_KEY or not isinstance(value,str) or key in ('dns','layouts'):continue
  choices={r['id'] for r in info.get('time_zones',[])} if key=='time_zone' else {r['id'] for r in info.get('power_plans',[])} if key=='power_plan' else BY_KEY[key].choices
  if value in choices and not(key.endswith('_dc') and not info.get('battery')):settings[key]=value
 profile={'version':1,'settings':settings,'languages':copy.deepcopy(info.get('languages',[])),'audio':[{'id':r['id'],'volume':r['volume'],'mute':r['mute']} for r in info.get('endpoints',[]) if r.get('controllable') and type(r.get('volume'))==int and type(r.get('mute'))==bool],'brightness':[{'id':r['id'],'value':r['value']} for r in info.get('brightness',[]) if type(r.get('value'))==int]}
 saved_plan(profile)
 from .installed_apps import match_app
 apps=sorted({ident for r in programs if (ident:=match_app(r.get('name',''))) in APPS})
 return {'title':'Набор перед переустановкой','profile':profile,'reinstall_plan':{'version':1,'apps':apps},'programs':programs,'driver_backups':backups,'display_snapshot':[{k:r[k] for k in ('id','name','current','orientation','x','y','primary') if k in r} for r in info.get('displays',[])],'note':'Сохраните профиль настроек, отдельный список для установки программ и копии драйверов. Это не резервная копия личных файлов, лицензий, паролей, BIOS или всех параметров Windows. Режимы экранов приведены для справки и требуют выбора на доступном оборудовании.'}
