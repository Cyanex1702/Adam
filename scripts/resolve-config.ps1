function Update-AdamConfigPath {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    if (-not $env:ADAM_CONFIG -or (Test-Path -LiteralPath $env:ADAM_CONFIG -PathType Leaf)) {
        return
    }
    # A previously launched shell may retain the absolute path of this moved project.
    $formerFolder = Split-Path -Leaf (Split-Path -Parent $env:ADAM_CONFIG)
    $projectFolder = Split-Path -Leaf $ProjectRoot
    $candidate = Join-Path $ProjectRoot (Split-Path -Leaf $env:ADAM_CONFIG)
    if ($formerFolder -eq $projectFolder -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $env:ADAM_CONFIG = $candidate
        Write-Host "Using relocated project configuration: $candidate"
        return
    }
    throw 'ADAM_CONFIG points to a missing file. Set it to your current configuration or clear it.'
}
