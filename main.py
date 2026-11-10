"""Run: python main.py [--demo] [--no-browser] [--port 0]."""
import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from winpilot.server import Application, create_server
from winpilot.demo import Demo
from winpilot.windows import Windows
from winpilot.instance import InstanceLock

def launch_window(url,geometry=None):
    if os.name=='nt':
        for variable in ['PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA']:
            base=os.environ.get(variable)
            if not base: continue
            edge=Path(base)/'Microsoft/Edge/Application/msedge.exe'
            if edge.exists():
                g=geometry or {};w=g.get('width',1240);h=g.get('height',860)
                options=[str(edge),'--app='+url,f'--window-size={w},{h}','--no-first-run']
                if 'left' in g and 'top' in g:options.append(f"--window-position={g['left']},{g['top']}")
                subprocess.Popen(options,creationflags=0x08000000)
                return
    webbrowser.open(url)

def main():
    p=argparse.ArgumentParser(description='Krolik Control — настройка Windows')
    p.add_argument('--demo',action='store_true',help='Демо без изменения системы')
    p.add_argument('--data-dir',default=None,help='Каталог локальных профилей и журналов')
    p.add_argument('--wait-instance',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--expected-user',default=None,help=argparse.SUPPRESS)
    p.add_argument('--no-browser',action='store_true'); p.add_argument('--port',type=int,default=0)
    args=p.parse_args()
    if os.name!='nt' and not args.demo:
        p.error('Реальный режим доступен только в Windows. Для просмотра: --demo')
    if os.name=='nt' and args.expected_user:
        import re
        output=subprocess.check_output(['whoami.exe','/user','/fo','csv','/nh'],creationflags=0x08000000).decode(errors='replace')
        sid=re.search(r'S-1-(?:[0-9]+-)*[0-9]+',output)
        if not sid or sid.group()!=args.expected_user:
            raise RuntimeError('Для запуска выбран другой аккаунт администратора. Откройте Krolik Control обычным запуском из своего аккаунта.')
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    if args.demo: directory=Path(os.environ.get('TEMP',str(Path.home())))/'WinPilot-Demo'
    else: directory=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WinPilot'/'sessions'
    if args.data_dir:directory=Path(args.data_dir)
    instance=InstanceLock(directory)
    if not instance.acquire(15 if args.wait_instance else 0):
        if not instance.activate():raise RuntimeError('Krolik Control уже работает. Подождите завершения запуска и откройте его окно.')
        return
    app=Application(Demo() if args.demo else Windows(),base/'ui',directory,args.demo)
    server=create_server(app,args.port)
    url=f'http://127.0.0.1:{server.server_port}/#{app.token}'
    if sys.stdout: print('Krolik Control запущен: '+url,flush=True)
    app.scan_inventory()
    instance.publish(server.server_port,app.token)
    if not args.no_browser: launch_window(url,app.workspace.value.get('ui',{}).get('window'))
    if os.name=='nt' and not args.demo and not args.no_browser:
        from winpilot.desktop_bridge import DesktopBridge
        app.desktop=DesktopBridge(app,lambda:launch_window(url,app.workspace.value.get('ui',{}).get('window')))
        app.desktop.start()
    def cleanup_idle():
        while True:
            time.sleep(15)
            if time.monotonic()-app.last_seen>120 and not app.lifetime_connections and not app.engine.snapshot()['running'] and not app.care.state['running'] and not app.toolbox.state['running'] and not any(v.get('status')=='running' for v in app.state()['tasks'].values()):
                server.shutdown(); return
    threading.Thread(target=cleanup_idle,daemon=True).start()
    try: server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt: pass
    finally:
        if app.desktop:app.desktop.close()
        app.pc.close();app.toolbox.close();app.driver_sources.cancel.set();app.archives.cancel.set()
        app.engine.cancel.set();app.care.stop();app.backend.display_guard.restore_pending()
        if not app.engine.snapshot()['running'] and hasattr(app.backend,'stop_processes'):app.backend.stop_processes()
        server.server_close();instance.close()

if __name__=='__main__':
    try: main()
    except Exception as exc:
        import traceback
        details=traceback.format_exc()
        if sys.stderr: print(details,file=sys.stderr)
        if os.name=='nt':
            ctypes=__import__('ctypes')
            ctypes.windll.user32.MessageBoxW(None,str(exc),'Krolik Control — ошибка запуска',0x10)
        raise SystemExit(1)
