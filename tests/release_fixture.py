"""Demo backend with two outputs to test an actual role change and undo."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from winpilot.demo import Demo
from winpilot.server import Application,create_server
p=argparse.ArgumentParser();p.add_argument('--data-dir',required=True);p.add_argument('--pending',action='store_true');a=p.parse_args()
b=Demo()
for e in b.info['endpoints']:e['default_roles']=[0,1,2]
b.info['endpoints'].append(dict(b.info['endpoints'][0],id='demo-headphones',name='Наушники USB',default=False,default_roles=[]))
app=Application(b,Path(__file__).resolve().parents[1]/'ui',a.data_dir,True)
if a.pending:
 op={'kind':'setting','key':'mouse_speed','value':'12','title':'Скорость указателя: 12','_journal':'apply-100.jsonl','_index':0}
 app.engine.logfile=Path(a.data_dir)/'apply-100.jsonl';app.engine.state.update(items=[dict(op,status='unverified')],log=str(app.engine.logfile),finished=True);app.engine.record(0,'unverified','Чтение недоступно');app.engine.pending.add(op,'unverified','Чтение недоступно');app.engine.history=app.engine._history();app.workspace.save({**app.workspace.value,'draft':{'version':1,'settings':{'mouse_speed':'12'}}})
app.scan_inventory();server=create_server(app)
print(f'http://127.0.0.1:{server.server_port}/#{app.token}',flush=True)
try:server.serve_forever()
finally:app.pc.close();server.server_close()
