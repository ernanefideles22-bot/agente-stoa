$ErrorActionPreference = "Stop"

$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "STOA Control.lnk"
$startMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "STOA"
$menuShortcut = Join-Path $startMenuDir "STOA Control.lnk"

foreach ($path in @($desktopShortcut, $menuShortcut)) {
    if (Test-Path $path) {
        Remove-Item $path -Force
    }
}

if (Test-Path $startMenuDir) {
    Remove-Item $startMenuDir -Force -Recurse -ErrorAction SilentlyContinue
}

Write-Host "Atalhos do STOA Control removidos."
