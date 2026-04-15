$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Removendo STOA local..."

& (Join-Path $projectRoot "disable-stoa-autostart.ps1")
& (Join-Path $projectRoot "remove-stoa-web-shortcuts.ps1")
& (Join-Path $projectRoot "stop-stoa-supervisor.ps1")
& (Join-Path $projectRoot "stop-stoa-tray.ps1")
& (Join-Path $projectRoot "stop-stoa-voice-daemon.ps1")
& (Join-Path $projectRoot "stop-stoa-daemon.ps1")

Write-Host ""
Write-Host "STOA removido do logon e processos principais encerrados."
