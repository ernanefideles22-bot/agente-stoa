$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot ".env.safe"

if (-not (Test-Path $envPath)) {
    throw "Crie $envPath a partir de .env.safe.example antes de iniciar."
}

docker compose -f (Join-Path $projectRoot "docker-compose.safe.yml") up -d --build

$hostPort = 18000
$portLine = Get-Content $envPath | Where-Object { $_ -match '^HOST_PORT=' } | Select-Object -First 1
if ($portLine) {
    $parsed = ($portLine -split '=', 2)[1].Trim()
    if ($parsed) {
        $hostPort = $parsed
    }
}

Write-Host "STOA Agent disponível em http://127.0.0.1:$hostPort"
