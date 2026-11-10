$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
py -3 -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
py -3 -m venv .portable-build\venv
if ($LASTEXITCODE -ne 0) { throw 'Cannot create build environment' }
$python = Join-Path $PSScriptRoot '.portable-build\venv\Scripts\python.exe'
& $python -m pip install 'ziglang==0.15.2'
if ($LASTEXITCODE -ne 0) { throw 'Cannot install compiler' }
& $python build_portable.py --output dist\KrolikControl
if ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }
Write-Host 'Ready: dist\KrolikControl\KrolikControl.exe; keep the data folder next to it.'
