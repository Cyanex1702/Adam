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
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'ADAM'
$selectedDataRoot = if ($env:ADAM_DATA_DIR) { $env:ADAM_DATA_DIR } else { $runtimeRoot }
if (Test-Path -LiteralPath (Join-Path $selectedDataRoot 'config\model-selection.json')) {
    Write-Host 'Using the finalized model selection; ADAM manages its registered runtime.'
    $command = if ($Api) { 'serve' } else { 'chat' }
    & "$PSScriptRoot\dev.ps1" -Command $command -Mode $Mode
    exit $LASTEXITCODE
}
$serverExe = Join-Path $runtimeRoot 'runtime\llama\llama-server.exe'
$modelAlias = if ($Uncensored) { 'qwen3-4b-abliterated' } else { 'qwen3-4b-instruct' }
$modelPath = Join-Path $runtimeRoot "models\$modelAlias.gguf"
if (-not (Test-Path -LiteralPath $serverExe) -or -not (Test-Path -LiteralPath $modelPath)) {
    throw 'Local model/runtime missing. Run scripts\setup-model.ps1 first.'
}
if (-not $env:ADAM_CONFIG) {
    $profile = if ($Uncensored) { 'adam.uncensored.toml' } else { 'adam.compact.toml' }
    $env:ADAM_CONFIG = Join-Path (Get-Location) $profile
}
$ownedProcess = $null
try {
    $ready = $false
    try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8080/health' -TimeoutSec 2).status -eq 'ok' }
    catch { $ready = $false }
    if (-not $ready) {
        $deviceArgs = if ($Cpu) { '--device none -ngl 0' } else { '--device Vulkan0 -ngl 99' }
        $samplingArgs = if ($Uncensored) { '--top-p 0.95 --top-k 20 --min-p 0' } else { '--top-p 0.8 --top-k 20 --min-p 0' }
        $arguments = "-m `"$modelPath`" --alias $modelAlias --host 127.0.0.1 " +
            "--port 8080 -c 4096 -t 3 --threads-batch 3 --parallel 1 --jinja " +
            "--reasoning-budget 0 --no-webui --no-agent --no-slots --log-disable " +
            "--cors-origins http://127.0.0.1:8765 --no-cors-credentials --poll 0 --poll-batch 0 $deviceArgs $samplingArgs"
        $ownedProcess = Start-Process -FilePath $serverExe -ArgumentList $arguments -PassThru -WindowStyle Hidden
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            if ($ownedProcess.HasExited) { throw 'Model server failed to start. Retry with -Cpu.' }
            try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8080/health' -TimeoutSec 2).status -eq 'ok' }
            catch { $ready = $false }
            if ($ready) { break }
            Start-Sleep -Seconds 1
        }
        if (-not $ready) { throw 'Model load timed out.' }
    }
    $modelIds = (Invoke-RestMethod 'http://127.0.0.1:8080/v1/models' -TimeoutSec 5).data.id
    if ($modelAlias -notin $modelIds) { throw 'Port 8080 serves another model; stop it first.' }
    Write-Host 'Model ready. ADAM starts next; closing this session stops the model if this script started it.'
    $command = if ($Api) { 'serve' } else { 'chat' }
    & "$PSScriptRoot\dev.ps1" -Command $command -Mode $Mode
    if ($LASTEXITCODE -ne 0) { throw 'ADAM failed to start; see the dependency/runtime error above.' }
}
finally {
    if ($ownedProcess -and -not $ownedProcess.HasExited) {
        Stop-Process -Id $ownedProcess.Id -ErrorAction SilentlyContinue
    }
}
