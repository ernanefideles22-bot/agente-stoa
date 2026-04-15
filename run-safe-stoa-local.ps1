$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot ".env.safe"
$depsPath = Join-Path $projectRoot ".pydeps"

if (-not (Test-Path $envPath)) {
    throw "Crie $envPath antes de iniciar."
}

if (-not (Test-Path $depsPath)) {
    throw "Dependências locais não encontradas. Rode .\\setup-safe-stoa-local.ps1 primeiro."
}

Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*$' -or $_ -match '^\s*#') {
        return
    }

    $parts = $_ -split '=', 2
    if ($parts.Length -eq 2) {
        [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

$env:PYTHONPATH = "$depsPath;$($env:PYTHONPATH)"

python -m uvicorn main:app --host 127.0.0.1 --port 18000 --app-dir (Join-Path $projectRoot "app")
