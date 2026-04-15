$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectRoot "logs"
$outLog = Join-Path $logDir "jarvis-supervisor.out.log"
$errLog = Join-Path $logDir "jarvis-supervisor.err.log"
$pidFile = Join-Path $logDir "jarvis-supervisor.pid"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existingPid) {
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Host "Jarvis supervisor já está rodando com PID $existingPid"
            exit 0
        }
    }
}

$process = Start-Process `
    -FilePath "powershell" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $projectRoot "jarvis-supervisor.ps1") `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id
Write-Host "Jarvis supervisor iniciado com PID $($process.Id)"
