$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$depsPath = Join-Path $projectRoot ".pydeps"

New-Item -ItemType Directory -Force -Path $depsPath | Out-Null
Get-ChildItem -Force $depsPath | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

python -m pip install --upgrade pip
python -m pip install --upgrade --target $depsPath -r (Join-Path $projectRoot "requirements.safe.txt")
