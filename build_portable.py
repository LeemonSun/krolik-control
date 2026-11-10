"""Windows x64 portable bundle and installer; buildable on Windows or Linux with Zig."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

from winpilot.version import VERSION
RUNTIME='3.14.8'
RUNTIME_URL=f'https://www.python.org/ftp/python/{RUNTIME}/python-{RUNTIME}-embed-amd64.zip'
RUNTIME_SHA256='a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310'

def write_payload(output,payload):
    """Publish only a closed, flushed archive; preserve the previous file on failure."""
    temporary=payload.with_name(payload.name+'.partial')
    try:
        with temporary.open('w+b') as stream:
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                for p in sorted(output.rglob('*')):
                    if p.is_file():z.write(p,Path('KrolikControl')/p.relative_to(output))
            stream.flush();os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary) as z:
            if z.testzip() is not None:raise RuntimeError('Portable archive failed integrity verification')
        os.replace(temporary,payload)
    finally:temporary.unlink(missing_ok=True)

def build(output,cache,zig,signing=None):
    def sign(file):
        if signing is None:return
        tool,thumbprint=signing
        if os.name!='nt' or not __import__('re').fullmatch('[0-9A-Fa-f]{40}',thumbprint) or not Path(tool).is_file():raise ValueError('Signing requires Windows, an explicit SignTool path and a certificate thumbprint')
        subprocess.run([str(tool),'sign','/sha1',thumbprint,'/fd','SHA256','/tr','https://timestamp.digicert.com','/td','SHA256',str(file)],check=True)
        subprocess.run([str(tool),'verify','/pa','/all',str(file)],check=True)
    root=Path(__file__).resolve().parent;output=Path(output).resolve();cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    import re
    resource=root/'launcher/launcher.rc';text=resource.read_text()
    numbers=','.join(VERSION.split('.')+['0'])
    text=re.sub(r'(FILEVERSION|PRODUCTVERSION) [0-9,]+',lambda m:m.group(1)+' '+numbers,text)
    text=re.sub(r'(VALUE "(?:FileVersion|ProductVersion)", ")[0-9.]+',lambda m:m.group(1)+VERSION,text)
    resource.write_text(text)
    manifest_file=root/'launcher/app.manifest';text=manifest_file.read_text()
    text=re.sub(r'(<assemblyIdentity version=")[^"]+',lambda m:m.group(1)+VERSION+'.0',text);manifest_file.write_text(text)
    archive=cache/f'python-{RUNTIME}-embed-amd64.zip'
    if not archive.exists():
        with urllib.request.urlopen(RUNTIME_URL,timeout=60) as response:archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=RUNTIME_SHA256:raise RuntimeError('Python runtime hash mismatch; no files were executed')
    if output.exists():shutil.rmtree(output)
    data=output/'data';data.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():raise RuntimeError('Corrupt Python runtime')
        bundle.extractall(data)
    shutil.copy2(root/'main.py',data/'main.py')
    for folder in ['winpilot','ui']:
        shutil.copytree(root/folder,data/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    res=cache/'launcher.res'
    subprocess.run([str(zig),'rc','/fo',str(res),'launcher.rc'],cwd=root/'launcher',check=True)
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s','-municode','-Wl,--subsystem,windows',str(root/'launcher'/'launcher.c'),str(res),'-lshell32','-luser32','-o',str(output/'KrolikControl.exe')],check=True)
    for debug in output.glob('*.pdb'):debug.unlink()
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s','-municode',str(root/'bench/benchmark.c'),'-ld3d11','-ldxgi','-o',str(data/'krolik-bench.exe')],check=True)
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s',str(root/'bench/memory.c'),'-o',str(data/'krolik-memory.exe')],check=True)
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s',str(root/'bench/graphics.c'),'-ldxgi','-o',str(data/'krolik-graphics.exe')],check=True)
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s',str(root/'bench/adl.c'),'-lwintrust','-o',str(data/'krolik-adl.exe')],check=True)
    shutil.copy2(root/'vendor/adl/LICENSE.txt',data/'ADL-LICENSE.txt')
    present=root/'assets/presentmon/PresentMon-2.6.0-x64.exe'
    from winpilot.game_capture import PRESENTMON_SHA
    if hashlib.sha256(present.read_bytes()).hexdigest()!=PRESENTMON_SHA:raise RuntimeError('PresentMon hash mismatch')
    shutil.copy2(present,data/present.name);shutil.copy2(root/'assets/presentmon/LICENSE.txt',data/'PresentMon-LICENSE.txt')
    manifest={'version':VERSION,'platform':'Windows x64','runtime':RUNTIME,'runtime_url':RUNTIME_URL,'runtime_sha256':RUNTIME_SHA256,'compiler':'Zig 0.15.2','windows_execution_tested':False,'exe_sha256':hashlib.sha256((output/'KrolikControl.exe').read_bytes()).hexdigest()}
    (cache/f'KrolikControl-{VERSION}-build.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    version_resource=resource.read_text().split('1 VERSIONINFO',1)[1]
    version_resource='1 VERSIONINFO'+version_resource
    compact_rc=cache/'uninstall.rc'
    compact_rc.write_text('#include <windows.h>\n2 RCDATA "'+str(root/'installer/install.ps1').replace('\\','/')+'"\n1 ICON "'+str(root/'assets/krolik-control.ico').replace('\\','/')+'"\n1 24 "'+str(root/'launcher/app.manifest').replace('\\','/')+'"\n'+version_resource.replace('KrolikControl.exe','uninstall-helper.exe').replace('Krolik Control Desktop','Krolik Control Uninstall'),encoding='utf-8')
    compact_res=cache/'uninstall.res';subprocess.run([str(zig),'rc','/fo',str(compact_res),str(compact_rc)],check=True)
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s','-municode','-Wl,--subsystem,windows',str(root/'installer/setup.c'),str(compact_res),'-lcrypt32','-luser32','-lshell32','-o',str(data/'uninstall-helper.exe')],check=True)
    for name in ['KrolikControl.exe','data/krolik-bench.exe','data/krolik-memory.exe','data/krolik-graphics.exe','data/krolik-adl.exe','data/uninstall-helper.exe']:sign(output/name)
    manifest.update(exe_sha256=hashlib.sha256((output/'KrolikControl.exe').read_bytes()).hexdigest(),signed=signing is not None)
    (cache/f'KrolikControl-{VERSION}-build.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    files=[{'path':p.relative_to(output).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.rglob('*')) if p.is_file() and p.name!='release-manifest.json']
    (data/'release-manifest.json').write_text(json.dumps({'product':'KrolikControl','version':VERSION,'files':files},ensure_ascii=False),encoding='utf-8')
    payload=cache/f'KrolikControl-{VERSION}-payload.zip'
    write_payload(output,payload)
    setup_rc=cache/'setup.rc'
    quote=lambda path:str(path).replace('\\','/').replace('"','\\"')
    setup_rc.write_text('#include <windows.h>\n1 RCDATA "'+quote(payload)+'"\n2 RCDATA "'+quote(root/'installer/install.ps1')+'"\n1 ICON "'+quote(root/'assets/krolik-control.ico')+'"\n1 24 "'+quote(root/'launcher/app.manifest')+'"\n'+version_resource.replace('KrolikControl.exe','KrolikControl_Setup.exe').replace('Krolik Control Desktop','Krolik Control Setup'),encoding='utf-8')
    setup_res=cache/'setup.res';subprocess.run([str(zig),'rc','/fo',str(setup_res),str(setup_rc)],check=True)
    setup=output.parent/f'KrolikControl_{VERSION}_Setup.exe'
    subprocess.run([str(zig),'cc','-target','x86_64-windows-gnu','-O2','-s','-municode','-Wl,--subsystem,windows',str(root/'installer/setup.c'),str(setup_res),'-lcrypt32','-luser32','-lshell32','-o',str(setup)],check=True)
    sign(setup)
    if payload.read_bytes() not in setup.read_bytes():raise RuntimeError('Setup does not contain the verified portable archive')
    if (root/'installer/install.ps1').read_bytes() not in setup.read_bytes():raise RuntimeError('Setup script resource is outdated')
    print('Portable bundle:',output);print('Setup:',setup)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='dist/KrolikControl');p.add_argument('--cache',default='.portable-build/cache');p.add_argument('--zig');p.add_argument('--sign-tool');p.add_argument('--certificate-thumbprint');a=p.parse_args()
    if bool(a.sign_tool)!=bool(a.certificate_thumbprint):p.error('Supply both --sign-tool and --certificate-thumbprint')
    zig=a.zig
    if not zig:
        spec=importlib.util.find_spec('ziglang')
        if spec:zig=str(Path(spec.origin).parent/('zig.exe' if os.name=='nt' else 'zig'))
        else:zig=shutil.which('zig')
    if not zig:raise SystemExit('Install Zig 0.15.2 or pip install ziglang==0.15.2')
    build(a.output,a.cache,zig,(a.sign_tool,a.certificate_thumbprint) if a.sign_tool else None)
