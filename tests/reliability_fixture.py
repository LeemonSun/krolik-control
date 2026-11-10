"""Explicit test fixture with multiple devices and repeatable failures."""
import copy,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
import winpilot.care_windows as care_windows
from winpilot.demo import Demo
from winpilot.server import Application,create_server
original_demo=care_windows.demo_run
def demo_run(c,kind,body):
    if kind=='observe':
        for i in range(12):
            c.stage('Наблюдение · '+str(i+1));c.cancel.wait(.2)
    return original_demo(c,kind,body)
care_windows.demo_run=demo_run
class App(Application):
    def __init__(self,directory):
        b=Demo();b.info['endpoints'] += [dict(b.info['endpoints'][0],id='demo-output-2',name='Наушники USB',default=False),dict(b.info['endpoints'][1],id='demo-microphone-2',name='Микрофон гарнитуры',default=False)]
        super().__init__(b,Path(__file__).parents[1]/'ui',directory,True);self.devices=copy.deepcopy(b.info['endpoints']);self.audio_runs=0;self.fail_audio=False;self.fail_apply=False
        apply_demo=b.apply_demo
        def apply(op):
            if self.fail_apply and op['kind']=='setting':time.sleep(1.3);raise RuntimeError('Fixture: setting rejected')
            return apply_demo(op)
        b.apply_demo=apply
    def task(self,name,fn):
        if name=='audio_test':
            original=fn
            def fn():
                self.audio_runs+=1;time.sleep(.25)
                if self.fail_audio:raise RuntimeError('Fixture: audio endpoint unplugged')
                return original()
        return super().task(name,fn)
    def post(self,path,body):
        if path=='/api/fixture':
            with self.lock:
                if 'devices' in body:
                    rows=copy.deepcopy(self.devices)
                    if body['devices']=='none':rows=[]
                    if body['devices']=='primary':rows=[r for r in rows if not r['id'].endswith('-2')]
                    self.backend.info['endpoints']=rows;self.info['endpoints']=copy.deepcopy(rows);self.data_revision+=1
                if body.get('report'):
                    report={'id':'fixture-report','kind':'audio','title':'Проверка нескольких устройств','time':time.time(),'demo':True,'metrics':{},'findings':[{'id':str(i),'title':'Устройство '+str(i+1),'detail':'Проверяем подключение, громкость и доступность устройства. Результат проверки останется на странице.','level':'info','action':None} for i in range(28)]}
                    self.care.state['reports']=[report];self.care.publish()
                if body.get('tick'):
                    self.care.state['reports'][0]['metrics']['duration_s']=body['tick'];self.care.publish()
                if 'fail_apply' in body:self.fail_apply=body['fail_apply']
                if 'fail_audio' in body:self.fail_audio=body['fail_audio']
                return {'audio_runs':self.audio_runs}
        return super().post(path,body)
app=App(sys.argv[1]);server=create_server(app);app.scan_inventory();print(f'http://127.0.0.1:{server.server_port}/#{app.token}',flush=True);server.serve_forever(poll_interval=.1)
