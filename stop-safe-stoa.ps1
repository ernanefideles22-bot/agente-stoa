$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

docker compose -f (Join-Path $projectRoot "docker-compose.safe.yml") down
