"""Explicit demo fixture. Never used as a Windows fallback."""
import copy
import time
from .native import DisplayGuard

INFO={
 'hostname':'DEMO-PC','os':'Windows 11 Pro · демонстрационные данные','build':'26100','cpu':['AMD Ryzen 7 7800X3D'],
 'gpu':['AMD Radeon RX 6650 XT'],'ram':32,'machine':'Desktop PC','admin':False,'winget':True,'battery':False,
 'network':[{'id':8,'name':'Ethernet','description':'Realtek 2.5GbE','status':'Up','dns':['192.168.1.1']}],
 'language_options':[{'id':a,'name':n} for a,n in [('ru-RU','Русский'),('en-US','Английский (США)'),('de-DE','Немецкий'),('fr-FR','Французский')]],'languages':['ru-RU','en-US'],'audio':[{'Name':'Realtek Audio','Status':'OK'},{'Name':'AMD High Definition Audio','Status':'OK'}],
 'startup':[{'Name':'Windows Security','Location':'Registry','User':'Demo'}], 'brightness':[],
 'power_plans':[{'id':'381b4222-f694-41f0-9685-ff5bb260df2e','name':'Сбалансированная'},{'id':'8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c','name':'Высокая производительность'}],
 'endpoints':[{'id':'demo-output','name':'Динамики (Realtek Audio)','form_factor':1,'flow':0,'default':True,'controllable':True,'volume':45,'mute':False},{'id':'demo-microphone','name':'Микрофон (USB Audio)','form_factor':4,'flow':1,'default':True,'controllable':True,'volume':70,'mute':False}],
 'board':{'Manufacturer':'MSI','Product':'B650 Gaming Plus'},'bios':{'Manufacturer':'American Megatrends','SMBIOSBIOSVersion':'1.A0'},'disks':[{'name':'NVMe SSD','size':1000,'bus':'SCSI'}],
 'settings':{'theme':'dark','extensions':'off','hidden':'off','layouts':'ru-en','mouse_speed':'10','mouse_accel':'on','screen_ac':'10','sleep_ac':'30','power_plan':'381b4222-f694-41f0-9685-ff5bb260df2e'},
 'displays':[{'id':'demo-display-1','name':'27″ Gaming Monitor','gpu':'AMD Radeon RX 6650 XT','primary':True,'x':0,'y':0,'current':'2560x1440@144','orientation':0,'modes':[{'id':f'{w}x{h}@{hz}','width':w,'height':h,'hz':hz} for w,h,hz in [(2560,1440,180),(2560,1440,144),(2560,1440,120),(2560,1440,60),(1920,1080,144),(1920,1080,60)]]},
 {'id':'demo-display-2','name':'24″ Secondary Monitor','gpu':'AMD Radeon RX 6650 XT','primary':False,'x':2560,'y':0,'current':'1920x1080@60','orientation':0,'modes':[{'id':'1920x1080@60','width':1920,'height':1080,'hz':60}]}]
}
DRIVERS=[{'id':str(i),'name':n,'category':c,'status':'OK' if i!=4 else 'Error','problem':0 if i!=4 else 28,'provider':p,'version':v,'date':'2026-06-12','inf':'oem12.inf','hardware_ids':['DEMO\\'+str(i)],'compatible_ids':[]} for i,(n,c,p,v) in enumerate([
 ('AMD Radeon RX 6650 XT','Display','Advanced Micro Devices','32.0.21001.9024'),('AMD Ryzen chipset','System','AMD','6.10.17'),('Realtek 2.5GbE','Net','Realtek','10.74.1128'),('Realtek Audio','MEDIA','Realtek','6.0.9700'),('Неизвестное устройство','Unknown','','')])]
# Large explicit fixture exercises prioritization without requiring a Windows host.
DRIVERS += [dict(id='demo-cpu-'+str(i),name='AMD Ryzen 7 7800X3D',category='Processor',status='OK',problem=0,provider='Microsoft',version='10.0.26100.1',date='',inf='cpu.inf',hardware_ids=['DEMO-CPU'],compatible_ids=[]) for i in range(16)]
DRIVERS += [dict(id='demo-system-'+str(i),name='Системное устройство '+str(i+1),category='System',status='OK',problem=0,provider='Microsoft',version='10.0.26100.1',date='',inf='machine.inf',hardware_ids=[],compatible_ids=[]) for i in range(179)]
class Demo:
    def __init__(self):
        self.info=copy.deepcopy(INFO);self.info['time_zones']=[{'id':'Russian Standard Time','name':'Москва · UTC+03:00'},{'id':'UTC','name':'UTC'}];self.info['settings']['time_zone']='Russian Standard Time';self.display_guard=DisplayGuard();self.installed={'Mozilla.Firefox':'1.0.demo','Valve.Steam':'1.0.demo'};self.upgraded=set()
        self.startup_rows=[{'id':'a'*64,'name':'Steam','enabled':True,'controllable':True,'source':'Пользователь · пример'},{'id':'b'*64,'name':'Windows Security','enabled':True,'controllable':False,'source':'Все пользователи · пример'}]
    def device_inventory(self):return {k:copy.deepcopy(self.info[k]) for k in ('displays','endpoints')}
    def inventory(self): time.sleep(.2); return copy.deepcopy(self.info)
    def drivers(self): time.sleep(.2); return copy.deepcopy(DRIVERS)
    def search_updates(self,kind):
        time.sleep(.2)
        return [{'id':('d' if kind=='Driver' else 'a')*8+'-0000-0000-0000-000000000001','revision':1,'name':'AMD display driver · пример' if kind=='Driver' else 'Накопительное обновление Windows · пример','size':125.4,'driver':kind=='Driver','hardware_id':'DEMO\\0' if kind=='Driver' else '', 'category':'Display' if kind=='Driver' else ''}]
    def apply_demo(self,op):
        k,key,value=op['kind'],op['key'],op['value']
        if k=='package_manager':self.info['winget']=True
        if k=='setting':self.info['settings'][key]=value
        if k=='audio':
            for r in self.info['endpoints']:
                if r['id']==key:r.update({x:y for x,y in value.items() if x!='id'})
        if k=='audio_default':
            for r in self.info['endpoints']:
                if r['flow']!=value['flow']:continue
                roles=set(r.get('default_roles',([1] if r.get('default') else [])));roles.discard(value['role'])
                if r['id']==key:roles.add(value['role'])
                r['default_roles']=sorted(roles);r['default']=1 in roles
        if k=='brightness':
            for r in self.info['brightness']:
                if r['id']==key:r['value']=value
        if k=='display':
            for r in self.info['displays']:
                if r['id']==key:r.update(current=value,orientation=op['orientation'])
        if k=='languages':self.info['languages']=value;self.info['settings'].pop('layouts',None)
        if k=='layout':
            for r in self.info['displays']:
                selected=next(v for v in value if v['id']==r['id']);r.update(x=selected['x'],y=selected['y'],primary=selected['primary'])
        if k in ('app','upgrade'):
            self.installed[key]='1.0.demo';self.upgraded.add(key)
        if k=='startup':self.set_startup(key,value)
    def prepare_package_manager(self):self.info['winget']=True;return {'ready':True,'message':'Демонстрация: установка подготовлена'}
    def programs(self):
        from .catalog import APPS
        return [{'id':a,'installed':a in self.installed,'version':self.installed.get(a,''),'available_version':'2.0.demo' if a=='Mozilla.Firefox' and a not in self.upgraded else None,'update_available':a=='Mozilla.Firefox' and a not in self.upgraded} for a in APPS]
    def startup(self):return copy.deepcopy(self.startup_rows)
    def set_startup(self,ident,enabled):
        for r in self.startup_rows:
            if r['id']==ident and r['controllable']:r['enabled']=enabled;return
        raise ValueError('Запись недоступна')
    def network_test(self):return {'adapters':[{'name':'Ethernet','ipv4':['192.168.1.2'],'gateway':['192.168.1.1']}],'dns':True,'https':True,'message':'Демонстрационные результаты; сеть не проверялась','checked':time.strftime('%Y-%m-%dT%H:%M:%S')}
    def activation(self): return [{'Name':'Windows Pro · пример','LicenseStatus':1}]
