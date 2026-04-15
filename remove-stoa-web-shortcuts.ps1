$ErrorActionPreference = "Stop"

$desktopDir = [Environment]::GetFolderPath("Desktop")
$startMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "STOA"

foreach ($path in @(
    (Join-Path $desktopDir "STOA Control.url"),
    (Join-Path $desktopDir "STOA.url"),
    (Join-Path $startMenuDir "STOA Control.url"),
    (Join-Path $startMenuDir "STOA.url")
)) {
    if (Test-Path $path) {
        Remove-Item $path -Force
    }
}

if (Test-Path $startMenuDir) {
    Remove-Item $startMenuDir -Force -Recurse -ErrorAction SilentlyContinue
}

Write-Host "Atalhos web do STOA removidos."
