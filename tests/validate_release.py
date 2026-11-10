"""Offline release integrity checks. Does not execute Windows binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
from winpilot.version import VERSION
from winpilot.game_capture import PRESENTMON_SHA
from build_portable import RUNTIME,RUNTIME_SHA256

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pe(p):
    b=p.read_bytes();assert b[:2]==b'MZ',str(p)
    offset=struct.unpack_from('<I',b,0x3c)[0]
    assert b[offset:offset+4]==b'PE\0\0',str(p)
    assert struct.unpack_from('<H',b,offset+4)[0]==0x8664,str(p)
    assert struct.unpack_from('<H',b,offset+24)[0]==0x20b,str(p)

def validate(output,cache):
    data=output/'data';setup=output.parent/f'KrolikControl_{VERSION}_Setup.exe'
    manifest=json.loads((data/'release-manifest.json').read_text())
    assert manifest['product']=='KrolikControl' and manifest['version']==VERSION
    actual={p.relative_to(output).as_posix():p for p in output.rglob('*') if p.is_file() and p.name!='release-manifest.json'}
    recorded={r['path']:r for r in manifest['files']}
    assert len(recorded)==len(manifest['files']) and set(actual)==set(recorded)
    for name,p in actual.items():assert sha(p)==recorded[name]['sha256'],name
    assert {p.name for p in output.iterdir()}=={'KrolikControl.exe','data'}
    assert not any(p.suffix in ('.md','.log','.pdb','.pyc') or '__pycache__' in p.parts or 'tests' in p.parts for p in output.rglob('*'))
    for folder in ('winpilot','ui'):
        original={p.relative_to(SOURCE/folder).as_posix():p for p in (SOURCE/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        packaged={p.relative_to(data/folder).as_posix():p for p in (data/folder).rglob('*') if p.is_file()}
        assert set(original)==set(packaged),folder
        for name,p in original.items():assert p.read_bytes()==packaged[name].read_bytes(),folder+'/'+name
    assert (SOURCE/'main.py').read_bytes()==(data/'main.py').read_bytes()
    assert sha(data/'PresentMon-2.6.0-x64.exe')==PRESENTMON_SHA
    assert sha(cache/f'python-{RUNTIME}-embed-amd64.zip')==RUNTIME_SHA256
    binaries=[p for p in output.rglob('*') if p.suffix.lower() in ('.exe','.dll','.pyd')]+[setup]
    for p in binaries:pe(p)
    payload=cache/f'KrolikControl-{VERSION}-payload.zip'
    with zipfile.ZipFile(payload) as z:
        assert z.testzip() is None
        zipped={i.filename for i in z.infolist() if not i.is_dir()}
        assert zipped=={'KrolikControl/'+p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
        for name in zipped:assert z.read(name)==(output.parent/name).read_bytes(),name
    assert payload.read_bytes() in setup.read_bytes()
    assert (SOURCE/'installer/install.ps1').read_bytes() in setup.read_bytes()
    assert (data/'ADL-LICENSE.txt').is_file() and (data/'PresentMon-LICENSE.txt').is_file()
    return dict(version=VERSION,manifest_files=len(recorded),pe_x64=len(binaries),source_parity=True,payload_parity=True,clean_distribution=True,setup_bytes=setup.stat().st_size,portable_bytes=payload.stat().st_size,unpacked_bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),runtime_sha256=RUNTIME_SHA256,windows_execution_tested=False,authenticode_signed=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('cache',type=Path);args=parser.parse_args()
    print(json.dumps(validate(args.output.resolve(),args.cache.resolve()),ensure_ascii=False,indent=2))
