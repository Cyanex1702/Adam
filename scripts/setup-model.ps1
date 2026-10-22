# Reproducible development helper, not the future guided installer.
param([switch]$Uncensored)
$ErrorActionPreference = 'Stop'
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'ADAM'
New-Item -ItemType Directory -Force -Path "$runtimeRoot\models","$runtimeRoot\runtime" | Out-Null
if ($Uncensored) {
    $modelPath = Join-Path $runtimeRoot 'models\qwen3-4b-abliterated.gguf'
    $modelUrl = 'https://huggingface.co/IamLucif3r/Qwen3-4B-Instruct-2507-Abliterated/resolve/c3248878a96c4b72cb4d2eb79069389c5827dbb9/Qwen3-4B-Instruct-2507-Abliterated-Q4_K_M.gguf'
    $modelHash = 'd416c35bfba822e0156cc5257d4f8cee49f9c83e4a947f86b91d97ee8b98893c'
} else {
    $modelPath = Join-Path $runtimeRoot 'models\qwen3-4b-instruct.gguf'
    $modelUrl = 'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
    $modelHash = '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
}
$zipPath = Join-Path $runtimeRoot 'runtime\llama-vulkan.zip'
$zipUrl = 'https://github.com/ggml-org/llama.cpp/releases/download/b11146/llama-b11146-bin-win-vulkan-x64.zip'
$zipHash = '55a378aa095b466979d85075234f66d7655c7a7483222af0c006c0e55b4d7bd6'
function Get-VerifiedDownload([string]$Url, [string]$Path, [string]$Hash) {
    if ((Test-Path -LiteralPath $Path) -and ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() -eq $Hash)) { return }
    if ((Test-Path -LiteralPath "$Path.part") -and ((Get-FileHash -LiteralPath "$Path.part" -Algorithm SHA256).Hash.ToLower() -eq $Hash)) {
        Move-Item -LiteralPath "$Path.part" -Destination $Path -Force
        return
    }
    & curl.exe -L --fail --retry 3 -C - --output "$Path.part" $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed; rerun to resume: $Url" }
    if ((Get-FileHash -LiteralPath "$Path.part" -Algorithm SHA256).Hash.ToLower() -ne $Hash) {
        throw "Checksum failed: $Path.part. The file was not installed."
    }
    Move-Item -LiteralPath "$Path.part" -Destination $Path -Force
}
Get-VerifiedDownload $modelUrl $modelPath $modelHash
Get-VerifiedDownload $zipUrl $zipPath $zipHash
$serverExe = Join-Path $runtimeRoot 'runtime\llama\llama-server.exe'
$receipt = Join-Path $runtimeRoot 'runtime\installed-sha256.txt'
if (-not ((Test-Path -LiteralPath $serverExe) -and (Test-Path -LiteralPath $receipt) -and
    ((Get-Content -LiteralPath $receipt -Raw).Trim() -eq $zipHash))) {
    $activeServer = Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" |
        Where-Object { $_.ExecutablePath -eq $serverExe }
    if ($activeServer) { throw 'Stop the existing model server before installing runtime files.' }
    Expand-Archive -LiteralPath $zipPath -DestinationPath "$runtimeRoot\runtime\llama" -Force -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $serverExe)) { throw 'Runtime extraction failed.' }
    Set-Content -LiteralPath $receipt -Value $zipHash
}
Write-Host "Verified model and llama.cpp installed under $runtimeRoot. No server started."
