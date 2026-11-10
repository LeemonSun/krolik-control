"""Isolated read-only file job. Own process is killable during slow filesystem I/O."""
import json
from pathlib import Path
import sys
import threading
from . import files

def main(spec):
    p=Path(spec)
    if p.stat().st_size>32768:raise ValueError('Слишком большое задание')
    job=json.loads(p.read_text(encoding='utf-8'));kind=job.get('kind');target=job.get('target');stop=threading.Event()
    if kind not in ('disk_map','duplicates','hash','rename_preview') or not isinstance(target,str):raise ValueError('Неверное задание')
    from .storage import linked
    identity=job.get('identity')
    target_path=Path(target);s=target_path.stat()
    if linked(target_path) or identity!=[s.st_dev,s.st_ino]:raise ValueError('Выбранный объект изменился')
    def stage(message):print(json.dumps({'phase':'progress','message':message},ensure_ascii=False),flush=True)
    if kind=='disk_map':r=files.analyze(target,stop,stage)
    elif kind=='duplicates':r=files.duplicates(target,stop,stage)
    elif kind=='rename_preview':r=files.rename_preview(target,job.get('find'),job.get('replace',''))
    else:
        sha=files.hash_file(target,stop,stage);expected=job.get('expected','').casefold();r={'title':'SHA-256 выбранного файла','name':Path(target).name,'sha256':sha,'matches':sha==expected if expected else None,'note':'SHA-256 проверяет содержимое относительно эталона, не безопасность файла.'}
    print(json.dumps({'phase':'result','result':r},ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:main(sys.argv[1])
    except Exception as e:print(json.dumps({'phase':'error','message':str(e)[:500]},ensure_ascii=False),flush=True);raise SystemExit(1)
