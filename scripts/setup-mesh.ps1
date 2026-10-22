param(
    [Parameter(Mandatory=$true)][string]$Address,
    [int]$Port = 9443,
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'ADAM')
)
$ErrorActionPreference = 'Stop'
if ($env:ADAM_DATA_DIR -and -not $PSBoundParameters.ContainsKey('DataDir')) { $DataDir = $env:ADAM_DATA_DIR }
$taskPython = Join-Path $env:LOCALAPPDATA 'ADAM\dev-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup.ps1 first.' }
$env:PYTHONPATH = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
& $taskPython -m adam.mesh.tls --data-dir $DataDir --address $Address --port $Port
if ($LASTEXITCODE -ne 0) { throw 'TLS setup failed. Stop the listener before changing its configuration.' }
Write-Host 'No firewall rule or certificate trust was changed. Follow docs/operations/mobile-mesh.md on Android.'
