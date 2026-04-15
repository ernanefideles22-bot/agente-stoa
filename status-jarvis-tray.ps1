$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot "logs\\jarvis-tray.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "Jarvis tray: parado"
    exit 0
}

$processId = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $processId) {
    Write-Host "Jarvis tray: parado"
    exit 0
}

$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($process) {
    Write-Host "Jarvis tray: ativo (PID $processId)"
} else {
    Write-Host "Jarvis tray: parado (PID órfão)"
}
