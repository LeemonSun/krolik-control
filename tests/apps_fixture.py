"""Browser-only clean-Windows fixture. Never imports the Windows backend."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from winpilot.demo import Demo
from winpilot.packages import SetupError
from winpilot.server import Application,create_server

class CleanDemo(Demo):
    def __init__(self):
        super().__init__();self.info['winget']=False;self.installed={};self.failed=False
    def apply_demo(self,op):
        if op['kind']=='package_manager' and not self.failed:
            self.failed=True
            raise SetupError('Не удалось подготовить установку программ. Проверьте интернет и повторите.',details='Fixture: download timeout')
        return super().apply_demo(op)

app=Application(CleanDemo(),Path(__file__).parents[1]/'ui',sys.argv[1],True)
server=create_server(app);app.scan_inventory()
print(f'http://127.0.0.1:{server.server_port}/#{app.token}',flush=True)
server.serve_forever(poll_interval=.1)
