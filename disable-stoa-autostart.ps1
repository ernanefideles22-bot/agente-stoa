$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

& (Join-Path $projectRoot "remove-stoa-scheduled-task.ps1")
& (Join-Path $projectRoot "remove-stoa-startup.ps1")

Write-Host "Autostart do STOA removido."
