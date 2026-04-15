$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

try {
    & (Join-Path $projectRoot "install-stoa-scheduled-task.ps1")
    Write-Host "Autostart do STOA configurado via tarefa agendada."
} catch {
    Write-Host "Falha ao criar tarefa agendada. Aplicando fallback via pasta Startup."
    & (Join-Path $projectRoot "install-stoa-startup.ps1")
    Write-Host "Autostart do STOA configurado via Startup do usuário."
}
