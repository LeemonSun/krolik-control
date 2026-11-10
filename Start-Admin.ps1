$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'main.py'
$sid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$launcher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($launcher) {
    Start-Process -FilePath $launcher.Source -ArgumentList @('-3', ('"' + $entry + '"'), '--expected-user', $sid) -WorkingDirectory $PSScriptRoot -Verb RunAs
} else {
    $python = Get-Command python.exe -ErrorAction Stop
    Start-Process -FilePath $python.Source -ArgumentList @(('"' + $entry + '"'), '--expected-user', $sid) -WorkingDirectory $PSScriptRoot -Verb RunAs
}
