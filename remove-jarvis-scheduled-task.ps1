$ErrorActionPreference = "Stop"

$taskName = "JarvisLocalSupervisor"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Tarefa agendada '$taskName' removida."
} else {
    Write-Host "Tarefa agendada '$taskName' não encontrada."
}
