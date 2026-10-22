$ErrorActionPreference = 'Stop'
$voiceRoot = Join-Path $env:LOCALAPPDATA 'ADAM\models\voice'
$revision = 'ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66'
$hfBase = "https://huggingface.co/Systran/faster-whisper-base/resolve/$revision"
$kokoroBase = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
$assets = @(
    @{ Name = 'faster-whisper-base/config.json'; Url = "$hfBase/config.json"; Hash = '56A6D8110D311F19C8F0471E562832C7527F146B567275BFCA59FCF7C184DA9A' },
    @{ Name = 'faster-whisper-base/model.bin'; Url = "$hfBase/model.bin"; Hash = 'D01C3014881C9C6F3133C182F3D2887EB6CA1C789A7538C5C007196857A0A6A9' },
    @{ Name = 'faster-whisper-base/tokenizer.json'; Url = "$hfBase/tokenizer.json"; Hash = 'FB7B63191E9BB045082C79FD742A3106A12C99513AB30DF4A0D47FA6CB6FD0AB' },
    @{ Name = 'faster-whisper-base/vocabulary.txt'; Url = "$hfBase/vocabulary.txt"; Hash = '34CE3FE1C5041027B3F8D42912270993F986DBC4BB34CF27F951E34A1E453913' },
    @{ Name = 'kokoro-v1.0.int8.onnx'; Url = "$kokoroBase/kokoro-v1.0.int8.onnx"; Hash = '6E742170D309016E5891A994E1CE1559C702A2CCD0075E67EF7157974F6406CB' },
    @{ Name = 'voices-v1.0.bin'; Url = "$kokoroBase/voices-v1.0.bin"; Hash = 'BCA610B8308E8D99F32E6FE4197E7EC01679264EFED0CAC9140FE9C29F1FBF7D' }
)
foreach ($asset in $assets) {
    $target = Join-Path $voiceRoot $asset.Name
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    if ((Test-Path -LiteralPath $target) -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq $asset.Hash) { continue }
    $partial = "$target.download"
    Invoke-WebRequest -Uri $asset.Url -OutFile $partial
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $asset.Hash) { throw "Voice asset checksum failed: $($asset.Name)" }
    Move-Item -LiteralPath $partial -Destination $target -Force
}
$manifest = @{ format = 1; stt = 'Systran/faster-whisper-base'; revision = $revision; tts = 'Kokoro-82M v1.0 int8'; assets = $assets }
[IO.File]::WriteAllText((Join-Path $voiceRoot 'manifest.json'), ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
Write-Host 'Local voice assets verified (about 256 MiB). Restart ADAM Desktop. No microphone was activated.'
