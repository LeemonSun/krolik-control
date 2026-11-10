"""Support summary with an explicit field allowlist, never a raw state dump."""
from .version import VERSION


def build(app):
    with app.lock:
        info=app.info or {};engine=app.engine.snapshot()
        return {'application':'Krolik Control','version':VERSION,'demo':app.demo,
                'windows':{'name':info.get('os'),'build':info.get('build'),'admin':bool(info.get('admin'))},
                'devices':{key:len(info.get(key,[])) for key in ('displays','endpoints','brightness','network')},
                'tasks':{name:row.get('status') for name,row in app.tasks.items()},
                'last_run':{'running':engine['running'],'finished':engine['finished'],
                            'items':[{'kind':row.get('kind'),'status':row.get('status'),'code':row.get('error_code')} for row in engine['items']]},
                'desktop':app.desktop.snapshot() if app.desktop else {'available':False},
                'privacy':'Names, serial numbers, addresses, file paths, profiles and request tokens are excluded.'}
