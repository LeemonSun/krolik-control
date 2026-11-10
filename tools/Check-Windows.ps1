[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Bundle,[string]$Report)
$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath $Bundle).Path
$python=Join-Path $root 'data\python.exe'
if(!(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Выберите распакованную папку KrolikControl с подпапкой data'}
if(!$Report){$Report=Join-Path ([Environment]::GetFolderPath('MyDocuments')) ('Krolik-Windows-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.json')}
& $python -I -B -m winpilot.windows_smoke --report $Report
if($LASTEXITCODE -ne 0){throw ('Проверка не пройдена. Отчёт: '+$Report)}
Write-Output ('Проверка чтения завершена. Отчёт: '+$Report)
Write-Output 'Установка, изменения настроек и работа оборудования требуют отдельных испытаний.'
