"""Run on Windows: python.exe -m winpilot.windows_smoke --report PATH.
Reads system interfaces only. Does not install, change settings or reboot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

def run():
    if os.name!='nt':raise RuntimeError('Этот прогон выполняется только на настоящей Windows')
    from .version import VERSION
    results=[]
    def test(name,fn,required=True):
        start=time.monotonic()
        try:
            value=fn();results.append({'name':name,'status':'passed','seconds':round(time.monotonic()-start,3),'result':value})
        except Exception as e:results.append({'name':name,'status':'failed' if required else 'unavailable','seconds':round(time.monotonic()-start,3),'error':str(e)[:1000]})
    from .native import enumerate_displays,read_input
    from .audio import enumerate_audio
    from .pc import FastCounters,volumes
    from .display_advanced import inventory
    from .firmware import firmware_mode
    test('displays',lambda:{'count':len(enumerate_displays())})
    test('input',lambda:{'count':len(read_input())})
    test('audio',lambda:{'count':len(enumerate_audio())},False)
    def counters():
        c=FastCounters();c.read();time.sleep(.2);r=c.read()
        if r['cpu'] is None or r['ram_total_gb'] is None:raise ValueError('Нет показателей Win32')
        return r
    test('cpu_ram',counters);test('volumes',lambda:{'count':len(volumes())});test('firmware_mode',firmware_mode)
    test('display_advanced',lambda:{'count':len(inventory())},False)
    root=Path(__file__).resolve().parents[1]
    def manifest():
        file=root/'release-manifest.json'
        if not file.is_file():return {'scope':'source_checkout','checked':0}
        m=json.loads(file.read_text(encoding='utf-8'));count=0
        for r in m['files']:
            p=(root.parent/r['path']).resolve()
            if root.parent not in p.parents or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:raise ValueError('Не совпал файл: '+r['path'])
            count+=1
        return {'checked':count}
    test('bundle_integrity',manifest)
    return {'version':VERSION,'time':time.time(),'platform':platform.platform(),'build':sys.getwindowsversion().build,'architecture':platform.machine(),'scope':'read_only_smoke','results':results,'passed':all(r['status']!='failed' for r in results),'limitations':'Не проверяет установки, изменения настроек, BIOS-записи, HDR-переключение, ETW-захват или физическую исправность оборудования.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',required=True);args=p.parse_args();result=run()
    from .workspace import atomic_json
    atomic_json(args.report,result);print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['passed'] else 1)
