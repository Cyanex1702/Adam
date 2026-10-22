param(
    [switch]$Install,
    [ValidateSet('serve','chat','init')][string]$Command = 'serve',
    [string]$EnvironmentRoot = (Join-Path $env:LOCALAPPDATA 'ADAM\dev-env'),
    [ValidateSet('owner','guest','demo')][string]$Mode = 'owner'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\resolve-config.ps1"
Update-AdamConfigPath -ProjectRoot (Get-Location).Path
$pythonExe = Join-Path $EnvironmentRoot 'Scripts\python.exe'
if (-not $env:ADAM_CONFIG -and (Test-Path -LiteralPath 'adam.local.toml')) {
    $env:ADAM_CONFIG = Join-Path (Get-Location) 'adam.local.toml'
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv $EnvironmentRoot
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
# Resolve Store-app redirection before both checking and installing dependencies.
$resolvedPythonExe = & $pythonExe -c 'import os,sys; print(os.path.realpath(sys.executable))'
if ($LASTEXITCODE -ne 0) { throw 'Python runtime resolution failed' }
$pythonExe = $resolvedPythonExe.Trim()
& $pythonExe "$PSScriptRoot\check-environment.py"
$needsRepair = $LASTEXITCODE -ne 0
if ($Install -or $needsRepair) {
    Write-Host 'Installing/updating ADAM dependencies in this PowerShell environment (internet may be needed once).'
    if (Test-Path -LiteralPath 'requirements.lock.txt') {
        & $pythonExe -m pip install -r requirements.lock.txt -e .
    } else {
        & $pythonExe -m pip install -e '.[dev]'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & $pythonExe "$PSScriptRoot\check-environment.py"
    if ($LASTEXITCODE -ne 0) { throw 'Environment verification failed after installation.' }
}
& $pythonExe -m adam.cli $Command --mode $Mode
exit $LASTEXITCODE
