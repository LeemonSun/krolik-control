"""One writer per workspace across processes; never unlink a live lock file."""
import json
import os
import time
import urllib.request
from pathlib import Path

class InstanceLock:
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.file=None
    def acquire(self,timeout=0):
        self.file=(self.directory/'instance.lock').open('a+b')
        self.file.seek(0,2)
        if not self.file.tell():self.file.write(b'0');self.file.flush()
        end=time.monotonic()+timeout
        while True:
            try:
                self.file.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                return True
            except (OSError,BlockingIOError):
                if time.monotonic()>=end:self.file.close();self.file=None;return False
                time.sleep(.05)
    def publish(self,port,token):
        from .workspace import atomic_json
        atomic_json(self.directory/'instance.json',{'port':port,'token':token,'pid':os.getpid()})
    def activate(self):
        # The endpoint is restricted to a loopback port; never follow file-provided URLs.
        deadline=time.monotonic()+3
        for _ in range(20):
            remaining=deadline-time.monotonic()
            if remaining<=0:return False
            try:
                data=json.loads((self.directory/'instance.json').read_text(encoding='utf-8'))
                port=data['port'];token=data['token']
                if type(port)!=int or not 1<=port<=65535 or not isinstance(token,str) or len(token)>200:return False
                req=urllib.request.Request(f'http://127.0.0.1:{port}/api/activate',data=b'{}',headers={'X-WinPilot-Token':token,'Content-Type':'application/json'})
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self,*args,**kwargs):return None
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
                with opener.open(req,timeout=min(.4,remaining)) as response:return response.status==200
            except (OSError,ValueError,KeyError):time.sleep(.1)
        return False
    def close(self):
        if self.file:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            self.file.close();self.file=None
