"""Simulated OEM enumerations for browser tests; never touches host firmware."""
import argparse
import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from winpilot.demo import Demo
from winpilot.server import Application,create_server
from winpilot.firmware import normalize

p=argparse.ArgumentParser();p.add_argument('--data-dir',required=True);args=p.parse_args()
a=Application(Demo(),Path(__file__).resolve().parents[1]/'ui',args.data_dir,True)
raw={'bios':[{'vendor':'Dell','version':'1.2.3','date':'2026-01-01'}],'board':[{'vendor':'Dell','model':'Fixture Board'}],'system':[{'vendor':'Dell','model':'Fixture PC'}],'cpu':[{'name':'Fixture CPU','virtualization':True}], 'boot':'boot1','encryption':True,'secure_boot':True,'memory':[{'slot':'A2','part':'Fixture RAM','vendor':'Test','bytes':16*1024**3,'configured':4800,'type':34},{'slot':'B2','part':'Fixture RAM','vendor':'Test','bytes':16*1024**3,'configured':4800,'type':34}], 'oem':{'provider':'dell','writer':True,'password':False,'rows':[{'name':'XMP Profile','current':'Disabled','choices':['Disabled','Profile 1'],'readonly':False,'physical':False},{'name':'WakeOnLAN','current':'Disabled','choices':['Disabled','Enabled'],'readonly':False,'physical':False}]}}
a.firmware._read=lambda:normalize(copy.deepcopy(raw),'uefi')
original=a.firmware.execute
def execute(i):
    r=original(i)
    if i['action']=='setting':
        row=next(s for s in raw['oem']['rows'] if s['name']==i['name']);row['current']=i['value']
    elif i['action']=='restart':
        raw['boot']='boot'+str(int(raw['boot'][4:])+1)
        raw['memory'][0]['configured']=raw['memory'][1]['configured']=6000 if raw['oem']['rows'][0]['current']=='Profile 1' else 4800
    return r
a.firmware.execute=execute
a.scan_inventory();server=create_server(a)
print(f'http://127.0.0.1:{server.server_port}/#{a.token}',flush=True)
try:server.serve_forever()
finally:a.pc.close();server.server_close()
