$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& "$PSScriptRoot\dev.ps1" -Command init
if ($LASTEXITCODE -ne 0) { throw 'Knowledge dependency setup failed.' }
$pythonExe = & "$env:LOCALAPPDATA\ADAM\dev-env\Scripts\python.exe" -c 'import os,sys;print(os.path.realpath(sys.executable))'
& $pythonExe -m adam.knowledge.setup
if ($LASTEXITCODE -ne 0) { throw 'Knowledge model setup failed.' }
