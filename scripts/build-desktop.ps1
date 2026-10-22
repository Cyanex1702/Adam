$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$buildRoot = Join-Path $env:LOCALAPPDATA 'ADAM\desktop-build'
$pythonWrapper = Join-Path $env:LOCALAPPDATA 'ADAM\dev-env\Scripts\python.exe'
$pythonExe = (& $pythonWrapper -c 'import os,sys;print(os.path.realpath(sys.executable))').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Resolve the ADAM development Python first.' }
& $pythonExe -m pip install -r requirements.lock.txt -r apps/desktop/requirements-build.txt -e .
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
$resources = Join-Path $projectRoot 'apps\desktop\src-tauri\resources'
New-Item -ItemType Directory -Path $resources -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'adam.compact.toml') -Destination (Join-Path $resources 'adam.compact.toml') -Force
& $pythonExe -m PyInstaller --clean --noconfirm --distpath $resources --workpath (Join-Path $buildRoot 'pyinstaller') scripts/desktop-service.spec
if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed.' }
. (Join-Path $PSScriptRoot 'desktop-build-env.ps1')
Set-Location -LiteralPath (Join-Path $projectRoot 'apps\desktop')
& npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
& npm.cmd run tauri -- build
if ($LASTEXITCODE -ne 0) { throw 'Native desktop build failed.' }
