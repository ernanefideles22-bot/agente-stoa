$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$depsPath = Join-Path $projectRoot ".pydeps"

if (-not (Test-Path $depsPath)) {
    throw "Dependências locais não encontradas em $depsPath."
}

[System.Environment]::SetEnvironmentVariable("PORT", "18000", "Process")
[System.Environment]::SetEnvironmentVariable("BIND_HOST", "127.0.0.1", "Process")
[System.Environment]::SetEnvironmentVariable("PYTHONPATH", $depsPath, "Process")

Set-Location $projectRoot
python .\app\main.py
