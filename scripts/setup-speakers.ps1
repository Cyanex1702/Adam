$ErrorActionPreference = 'Stop'
$pythonWrapper = Join-Path $env:LOCALAPPDATA 'ADAM\dev-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonWrapper)) { throw 'Run scripts/dev.ps1 -Install -Command init first.' }
$pythonExe = (& $pythonWrapper -c 'import os,sys;print(os.path.realpath(sys.executable))').Trim()
& $pythonExe (Join-Path $PSScriptRoot 'setup-speakers.py')
if ($LASTEXITCODE -ne 0) { throw 'Speaker model setup failed.' }
