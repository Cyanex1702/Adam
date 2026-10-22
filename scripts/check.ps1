$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$pythonExe = Join-Path $env:LOCALAPPDATA 'ADAM\dev-env\Scripts\python.exe'
$resolvedPythonExe = & $pythonExe -c 'import os,sys; print(os.path.realpath(sys.executable))'
if ($LASTEXITCODE -ne 0) { throw 'Python runtime resolution failed' }
$pythonExe = $resolvedPythonExe.Trim()
$env:MYPY_CACHE_DIR = Join-Path $env:LOCALAPPDATA 'ADAM\mypy-cache'
$env:RUFF_CACHE_DIR = Join-Path $env:LOCALAPPDATA 'ADAM\ruff-cache'
foreach ($check in @(@('-m','pytest','-q','-p','no:cacheprovider'),
                     @('-m','ruff','check','.'),
                     @('-m','ruff','format','--check','.'),
                     @('-m','mypy','backend/adam'),
                     @('-m','adam.evals.runner','--suite','full','--summary'))) {
    & $pythonExe @check
    if ($LASTEXITCODE -ne 0) { throw "Check failed: $check" }
}
