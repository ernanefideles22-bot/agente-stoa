$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Instalando STOA local..."

& (Join-Path $projectRoot "run-stoa-supervisor.ps1")
& (Join-Path $projectRoot "enable-stoa-autostart.ps1")
& (Join-Path $projectRoot "install-stoa-web-shortcuts.ps1")

Write-Host ""
Write-Host "STOA instalado."
Write-Host "Supervisor ativo, autostart configurado e atalhos web do STOA publicados."
Write-Host "Interface: http://127.0.0.1:18000"
