$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $projectRoot "logs\\jarvis-daemon.pid"
$startScript = Join-Path $projectRoot "run-safe-stoa-local.ps1"

if (-not (Test-Path $pidFile)) {
    Write-Host "Jarvis daemon: parado"
    exit 0
}

$processId = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $processId) {
    Write-Host "Jarvis daemon: parado"
    exit 0
}

$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if (-not $process) {
    Write-Host "Jarvis daemon: parado (PID órfão)"
    exit 0
}

$commandLine = ""
try {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($proc) {
        $commandLine = ($proc.CommandLine | Out-String).Trim()
    }
} catch {
}

if ($process.ProcessName -match "powershell|pwsh|python" -and $commandLine -match [Regex]::Escape($startScript)) {
    Write-Host "Jarvis daemon: ativo (PID $processId)"
} else {
    Write-Host "Jarvis daemon: parado (PID reciclado)"
}
