$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectRoot "logs"
$supervisorLog = Join-Path $logDir "jarvis-supervisor.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-SupervisorLog {
    param([string]$Message)
    Add-Content -Path $supervisorLog -Value ("{0} {1}" -f (Get-Date).ToString("s"), $Message)
}

function Ensure-ScriptRunning {
    param(
        [string]$RunScript,
        [string]$StatusScript
    )

    $statusOutput = & (Join-Path $projectRoot $StatusScript) 2>&1 | Out-String
    if ($statusOutput -match "ativo") {
        return
    }

    Write-SupervisorLog "Iniciando componente via $RunScript"
    & (Join-Path $projectRoot $RunScript) | Out-Null
}

Write-SupervisorLog "Supervisor iniciado"

while ($true) {
    try {
        Ensure-ScriptRunning -RunScript "run-jarvis-daemon.ps1" -StatusScript "status-jarvis-daemon.ps1"
        Ensure-ScriptRunning -RunScript "run-jarvis-voice-daemon.ps1" -StatusScript "status-jarvis-voice-daemon.ps1"
        Ensure-ScriptRunning -RunScript "run-jarvis-tray.ps1" -StatusScript "status-jarvis-tray.ps1"
    } catch {
        Write-SupervisorLog ("Erro no supervisor: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds 20
}
