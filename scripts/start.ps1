param([switch]$Cpu, [switch]$Api, [switch]$Uncensored, [switch]$Recovery,
    [ValidateSet('owner','guest','demo')][string]$Mode = 'owner')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\resolve-config.ps1"
Update-AdamConfigPath -ProjectRoot (Get-Location).Path
if ($Recovery) {
    $pythonExe = Join-Path $env:LOCALAPPDATA 'ADAM\dev-env\Scripts\python.exe'
    $resolvedPythonExe = & $pythonExe -c 'import os,sys; print(os.path.realpath(sys.executable))'
    & $resolvedPythonExe -m adam.resilience.cli recovery
    exit $LASTEXITCODE
}
if (-not $env:ADAM_CONFIG) {
    $profile = if ($Uncensored) { 'adam.uncensored.toml' } else { 'adam.compact.toml' }
    $env:ADAM_CONFIG = Join-Path (Get-Location) $profile
}
$env:ADAM_MANAGED_SOURCE = '1'
Write-Host 'ADAM manages its own model process. Closing this terminal stops its owned model.'
Write-Host 'CPU mode is the safe default. Use /performance priority for more CPU time.'
$command = if ($Api) { 'serve' } else { 'chat' }
& "$PSScriptRoot\dev.ps1" -Command $command -Mode $Mode
exit $LASTEXITCODE
