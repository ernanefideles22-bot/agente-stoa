$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot "logs\\jarvis-supervisor.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "Jarvis supervisor não está registrado."
    exit 0
}

$pid = Get-Content $pidFile -ErrorAction SilentlyContinue
if ($pid) {
    $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $pid -Force
        Write-Host "Jarvis supervisor parado."
    } else {
        Write-Host "PID registrado não está ativo."
    }
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
