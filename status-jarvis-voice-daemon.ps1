$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot "logs\\jarvis-voice.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "Jarvis voice daemon: parado"
    exit 0
}

$processId = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $processId) {
    Write-Host "Jarvis voice daemon: parado"
    exit 0
}

$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($process) {
    Write-Host "Jarvis voice daemon: ativo (PID $processId)"
} else {
    Write-Host "Jarvis voice daemon: parado (PID órfão)"
}
