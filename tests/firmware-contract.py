"""Execute real adapter scripts against isolated CIM doubles, not Windows hardware."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from winpilot.firmware import WRITE_PS,SETTING_TYPES

MOCK=r'''
function Get-CimInstance {
 [CmdletBinding()]param([string]$ClassName,[string]$Namespace,[int]$OperationTimeoutSec)
 switch($ClassName){
  Win32_ComputerSystem {[pscustomobject]@{Manufacturer=$manufacturer}}
  Lenovo_BiosSetting {[pscustomobject]@{CurrentSetting=('XMP Profile,'+$current)}}
  Lenovo_BiosPasswordSettings {[pscustomobject]@{PasswordState=$(if($locked){2}else{0})}}
  Lenovo_SetBiosSetting {[pscustomobject]@{Tag='setter'}}
  Lenovo_SaveBiosSettings {[pscustomobject]@{Tag='save'}}
  Lenovo_GetBiosSelections {[pscustomobject]@{Tag='selections'}}
  EnumerationAttribute {[pscustomobject]@{AttributeName='XMP Profile';CurrentValue=$current;PossibleValue=@('Disabled','Profile 1');ReadOnly=$readonly}}
  BIOSAttributeInterface {[pscustomobject]@{Tag='setter'}}
  PasswordObject {[pscustomobject]@{IsPasswordSet=$(if($locked){1}else{0})}}
  HP_BIOSEnumeration {[pscustomobject]@{Name='XMP Profile';CurrentValue=$current;PossibleValues=@('Disabled','Profile 1');IsReadOnly=[int]$readonly;RequiresPhysicalPresence=0}}
  HP_BIOSPassword {[pscustomobject]@{IsSet=$(if($locked){1}else{0})}}
  HP_BIOSSettingInterface {[pscustomobject]@{Tag='setter'}}
  default {throw ('Unexpected class '+$ClassName)}
 }
}
function Invoke-CimMethod {
 [CmdletBinding()]param($InputObject,[string]$MethodName,[hashtable]$Arguments)
 if($MethodName -eq 'GetBiosSelections'){return [pscustomobject]@{return='Success';Selections='Disabled,Profile 1'}}
 [Console]::Error.WriteLine('WRITE '+$MethodName)
 if($MethodName -eq 'SetAttribute'){
  if($Arguments.SecType -ne 0 -or $Arguments.SecHndCount -ne 0 -or $Arguments.AttributeName -cne 'XMP Profile' -or $Arguments.AttributeValue -cne 'Profile 1'){throw 'Wrong Dell arguments'}
  if($reject){return [pscustomobject]@{Status=3}};return [pscustomobject]@{Status=0}
 }
 if($MethodName -ceq 'SetBIOSSetting'){
  if($Arguments.Name -cne 'XMP Profile' -or $Arguments.Value -cne 'Profile 1' -or $Arguments.Password -cne '<utf-16/>'){throw 'Wrong HP arguments'}
  if($reject){return [pscustomobject]@{Return=6}};return [pscustomobject]@{Return=0}
 }
 if($MethodName -ceq 'SetBiosSetting'){
  if($Arguments.parameter -cne 'XMP Profile,Profile 1'){throw 'Wrong Lenovo arguments'}
  if($reject){return [pscustomobject]@{return='Access Denied'}};return [pscustomobject]@{return='Success'}
 }
 if($MethodName -eq 'SaveBiosSettings'){return [pscustomobject]@{return='Success'}}
 throw ('Unexpected method '+$MethodName)
}
'''
checks=[]
with tempfile.TemporaryDirectory() as d:
    for provider,maker in [('lenovo','Lenovo'),('dell','Dell Inc.'),('hp','HP')]:
        for scenario in ('success','locked','changed','bad-choice','rejected'):
            payload={'names':list(SETTING_TYPES),'provider':provider,'name':'XMP Profile','before':'Disabled','value':'Unknown' if scenario=='bad-choice' else 'Profile 1'}
            b64=base64.b64encode(json.dumps(payload).encode()).decode()
            code="$ErrorActionPreference='Stop';$p=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+b64+"'))|ConvertFrom-Json);\n"
            code+=f"$manufacturer='{maker}';$current='{'Profile 1' if scenario=='changed' else 'Disabled'}';$locked=${str(scenario=='locked').lower()};$readonly=$false;$reject=${str(scenario=='rejected').lower()};\n"+MOCK+WRITE_PS
            file=Path(d)/'case.ps1';file.write_text(code)
            r=subprocess.run([sys.argv[1],'-NoProfile','-NonInteractive','-File',str(file)],capture_output=True,text=True,timeout=15)
            if scenario in ('locked','changed','bad-choice'):
                assert r.returncode!=0,(provider,scenario,r.stdout,r.stderr)
                assert 'WRITE ' not in r.stderr,(provider,scenario,r.stderr)
            else:
                assert r.returncode==0,(provider,scenario,r.stdout,r.stderr)
                result=json.loads(r.stdout);assert result['accepted']==(scenario=='success'),(provider,scenario,result)
                assert r.stderr.count('WRITE ')==(2 if provider=='lenovo' and scenario=='success' else 1),(provider,scenario,r.stderr)
            checks.append(provider+': '+scenario)
print(json.dumps({'success':True,'checks':checks,'scope':'PowerShell 7 CIM doubles on Linux; not hardware execution'},indent=2))
