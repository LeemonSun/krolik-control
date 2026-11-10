"""Exercise installer transaction logic under PowerShell with Windows registry/COM mocked.
This does not claim Windows installer or registry compatibility.
"""
import hashlib,json,os,subprocess,tempfile,time,uuid,zipfile
from pathlib import Path

PWSH=os.environ.get('PWSH','pwsh')
SOURCE=Path(__file__).parents[1]/'installer/install.ps1'
MOCKS=r'''
$script:registryExists=Test-Path -LiteralPath $env:KC_REGISTRY
$script:registry=if($script:registryExists){Get-Content -LiteralPath $env:KC_REGISTRY -Raw|ConvertFrom-Json -AsHashtable}else{@{}}
$script:faultTriggered=$false
function Write-Registry {if($script:registryExists){ConvertTo-Json -InputObject $script:registry -Depth 8|Set-Content -LiteralPath $env:KC_REGISTRY}else{Microsoft.PowerShell.Management\Remove-Item -LiteralPath $env:KC_REGISTRY -ErrorAction SilentlyContinue}}
function Test-Path {param($LiteralPath,$Path);$target=if($LiteralPath){$LiteralPath}else{$Path};if($target -eq $env:KC_KEY){return $script:registryExists};Microsoft.PowerShell.Management\Test-Path -LiteralPath $target}
function Get-Item {param($LiteralPath);if($LiteralPath -ne $env:KC_KEY){return Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath};$item=[pscustomobject]@{};$item|Add-Member ScriptMethod GetValueNames {return @($script:registry.Keys)};$item|Add-Member ScriptMethod GetValueKind {param($name);return $script:registry[$name].kind};$item|Add-Member ScriptMethod GetValue {param($name,$default,$options);return $script:registry[$name].value};return $item}
function New-Item {param($Path,$ItemType,[switch]$Force);if($Path -eq $env:KC_KEY){$script:registryExists=$true;Write-Registry;return};Microsoft.PowerShell.Management\New-Item -Path $Path -ItemType $ItemType -Force:$Force}
function New-ItemProperty {param($Path,$Name,$Value,$PropertyType,[switch]$Force);$script:registry[$Name]=@{value=$Value;kind=$PropertyType};Write-Registry;if($env:KC_FAULT -eq 'registry' -and $Name -eq 'NoRepair' -and !$script:faultTriggered){$script:faultTriggered=$true;throw 'Injected registry failure'}}
function Remove-ItemProperty {param($LiteralPath,$Name);$script:registry.Remove($Name);Write-Registry}
function Remove-Item {param($LiteralPath,[switch]$Recurse,[switch]$Force);if($LiteralPath -eq $env:KC_KEY){$script:registryExists=$false;$script:registry=@{};Write-Registry;return};Microsoft.PowerShell.Management\Remove-Item -LiteralPath $LiteralPath -Recurse:$Recurse -Force:$Force -ErrorAction Stop}
function Get-CimInstance {param($ClassName,$Filter);return @()}
function New-Object {[CmdletBinding(DefaultParameterSetName='Type')]param([Parameter(ParameterSetName='COM')][string]$ComObject,[Parameter(ParameterSetName='Type',Position=0)][string]$TypeName,[Parameter(ParameterSetName='Type',Position=1)][object[]]$ArgumentList,[hashtable]$Property,[switch]$Strict);if(!$ComObject){return Microsoft.PowerShell.Utility\New-Object @PSBoundParameters};$shell=[pscustomobject]@{};$shell|Add-Member ScriptMethod CreateShortcut {param($path);$shortcut=[pscustomobject]@{path=$path;TargetPath='';WorkingDirectory='';IconLocation=''};$shortcut|Add-Member ScriptMethod Save {[IO.File]::WriteAllText($this.path,$this.TargetPath);if($env:KC_FAULT -eq 'shortcut' -and !$script:faultTriggered){$script:faultTriggered=$true;throw 'Injected shortcut failure'}};return $shortcut};return $shell}
function Expand-Archive {param($LiteralPath,$DestinationPath,[switch]$Force);if($env:KC_HOLD -eq 'yes'){[IO.File]::WriteAllText($env:KC_ENTERED,'locked');Start-Sleep -Milliseconds 1300};[IO.Compression.ZipFile]::ExtractToDirectory($LiteralPath,$DestinationPath,$true)}
'''
def quote(value):return "'"+str(value).replace("'","''")+"'"
def setup(base,old=False):
 base.mkdir(parents=True,exist_ok=True);root=base/'Programs/KrolikControl';registry=base/'registry.json';start=base/'Start/Krolik.lnk';desktop=base/'Desktop/Krolik.lnk';start.parent.mkdir();desktop.parent.mkdir()
 if old:
  root.mkdir(parents=True);(root/'old.txt').write_text('old installation');(root/'install-info.json').write_text(json.dumps({'product':'KrolikControl','version':'0.6.1'}));registry.write_text(json.dumps({'DisplayVersion':{'kind':'String','value':'0.6.1'},'NoModify':{'kind':'DWord','value':1}}));start.write_bytes(b'old start shortcut');desktop.write_bytes(b'old desktop shortcut')
 payload=base/'package.zip';content=b'new application';manifest={'product':'KrolikControl','version':'0.6.2','files':[{'path':'new.txt','sha256':hashlib.sha256(content).hexdigest()}]}
 with zipfile.ZipFile(payload,'w') as z:z.writestr('KrolikControl/new.txt',content);z.writestr('KrolikControl/data/release-manifest.json',json.dumps(manifest))
 script=SOURCE.read_text();lines=script.splitlines();lines[2]='$root='+quote(root);lines[3]='$key=$env:KC_KEY';lines[4]='$start='+quote(start);lines[5]='$desktop='+quote(desktop);script='\n'.join(lines).replace('[Security.Principal.WindowsIdentity]::GetCurrent().User.Value','$env:KC_MUTEX').replace("([Environment]::GetFolderPath('LocalApplicationData'))",quote(base/'Local'))
 harness=base/'harness.ps1';harness.write_text(MOCKS+'\n'+script)
 env={**os.environ,'KC_REGISTRY':str(registry),'KC_KEY':'RegistryMock','KC_MUTEX':uuid.uuid4().hex,'KC_ENTERED':str(base/'entered'),'KROLIK_SETUP_PAYLOAD':str(payload),'KROLIK_SETUP_MODE':'install','KROLIK_SETUP_DESKTOP':'yes'}
 return root,registry,start,desktop,harness,env

def run(harness,env):
 result=subprocess.run([PWSH,'-NoProfile','-NonInteractive','-File',str(harness)],env=env,capture_output=True,text=True,timeout=25)
 if result.returncode and not env.get('KC_FAULT') and env.get('KC_HOLD')!='no':
  for log in harness.parent.rglob('setup-error.txt'):print(log.read_text(),flush=True)
 return result
with tempfile.TemporaryDirectory(prefix='kc-installer-') as tmp:
 base=Path(tmp)
 root,reg,start,desktop,harness,env=setup(base/'success');result=run(harness,env);assert result.returncode==0,(result.stdout,result.stderr);assert (root/'new.txt').is_file();assert json.loads(reg.read_text())['DisplayVersion']['value']=='0.6.2';assert start.is_file() and desktop.is_file();print('PASS: successful first install (mock registry and shortcuts)')
 root,reg,start,desktop,harness,env=setup(base/'fresh-failure');env['KC_FAULT']='registry';result=run(harness,env);assert result.returncode==1,(result.stdout,result.stderr);assert not root.exists(),'Incomplete fresh install was retained';assert not reg.exists(),'Partial registration was retained';assert not start.exists() and not desktop.exists();print('PASS: first-install failure removes partial files and registration')
 root,reg,start,desktop,harness,env=setup(base/'update-failure',old=True);old=reg.read_text();env['KC_FAULT']='shortcut';result=run(harness,env);assert result.returncode==1,(result.stdout,result.stderr);assert (root/'old.txt').read_text()=='old installation';assert not (root/'new.txt').exists();assert json.loads(reg.read_text())==json.loads(old);assert start.read_bytes()==b'old start shortcut';assert desktop.read_bytes()==b'old desktop shortcut';print('PASS: failed update restores old files, registry values and exact shortcut bytes')
 root,reg,start,desktop,harness,env=setup(base/'concurrent');env['KC_HOLD']='yes';first=subprocess.Popen([PWSH,'-NoProfile','-NonInteractive','-File',str(harness)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  deadline=time.monotonic()+10
  while not Path(env['KC_ENTERED']).exists() and first.poll() is None and time.monotonic()<deadline:time.sleep(.02)
  assert Path(env['KC_ENTERED']).exists(),'First installer did not acquire lock';second=run(harness,{**env,'KC_HOLD':'no'});out,err=first.communicate(timeout=20);assert second.returncode==1,(second.stdout,second.stderr);assert first.returncode==0,(out,err);assert (root/'new.txt').is_file();print('PASS: simultaneous installer is rejected without changing first transaction')
 finally:
  if first.poll() is None:first.kill();first.communicate()
print('PASS: isolated transaction tests; real Windows registry/COM/install execution is not tested')
