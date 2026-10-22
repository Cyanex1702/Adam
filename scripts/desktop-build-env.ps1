$buildRoot = Join-Path $env:LOCALAPPDATA 'ADAM\desktop-build'
$env:CARGO_HOME = Join-Path $buildRoot 'cargo'
$env:RUSTUP_HOME = Join-Path $buildRoot 'rustup'
$env:CARGO_TARGET_DIR = Join-Path $buildRoot 'target'
$env:CARGO_BUILD_JOBS = '2'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Install Visual Studio C++ Build Tools first.' }
$adamVsRoot = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if (-not $adamVsRoot) { throw 'No installed MSVC x64 build tools were found.' }
$adamMsvcVersion = (Get-Content -LiteralPath (Join-Path $adamVsRoot 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt') -Raw).Trim()
$msvc = Join-Path $adamVsRoot ('VC\Tools\MSVC\' + $adamMsvcVersion)
$sdk = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows Kits\Installed Roots' -Name KitsRoot10).KitsRoot10
$adamSdkCandidates = @(Get-ChildItem -LiteralPath (Join-Path $sdk 'Include') -Directory | Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' -and (Test-Path -LiteralPath (Join-Path $_.FullName 'um')) } | Sort-Object { [version]$_.Name } -Descending)
if (-not $adamSdkCandidates.Count) { throw 'Install a Windows SDK with C++ headers first.' }
$sdkVersion = $adamSdkCandidates[0].Name
$env:PATH = "$env:CARGO_HOME\bin;$msvc\bin\Hostx64\x64;$sdk\bin\$sdkVersion\x64;$env:PATH"
$env:INCLUDE = "$msvc\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\shared;$sdk\Include\$sdkVersion\um;$sdk\Include\$sdkVersion\winrt"
$env:LIB = "$msvc\lib\x64;$sdk\Lib\$sdkVersion\ucrt\x64;$sdk\Lib\$sdkVersion\um\x64"
$env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = "$msvc\bin\Hostx64\x64\link.exe"
