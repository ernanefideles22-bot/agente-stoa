$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectRoot "logs"
$outLog = Join-Path $logDir "jarvis-daemon.out.log"
$errLog = Join-Path $logDir "jarvis-daemon.err.log"
$pidFile = Join-Path $logDir "jarvis-daemon.pid"
$startScript = Join-Path $projectRoot "run-safe-stoa-local.ps1"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-TrackedProcess {
    if (-not (Test-Path $pidFile)) {
        return $null
    }

    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if (-not $existingPid) {
        return $null
    }

    $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if (-not $existingProcess) {
        return $null
    }

    $commandLine = ""
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid" -ErrorAction SilentlyContinue
        if ($proc) {
            $commandLine = ($proc.CommandLine | Out-String).Trim()
        }
    } catch {
    }

    if ($existingProcess.ProcessName -match "powershell|pwsh|python" -and $commandLine -match [Regex]::Escape($startScript)) {
        return $existingProcess
    }

    return $null
}

$trackedProcess = Get-TrackedProcess
if ($trackedProcess) {
    Write-Host "Jarvis já está rodando com PID $($trackedProcess.Id)"
    exit 0
}

$process = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startScript `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id
Write-Host "Jarvis daemon iniciado com PID $($process.Id)"
