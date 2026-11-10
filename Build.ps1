# Canonical Windows build: portable folder plus a single-file setup executable.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Build-Portable.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
