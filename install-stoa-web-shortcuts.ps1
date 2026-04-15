$ErrorActionPreference = "Stop"

$desktopDir = [Environment]::GetFolderPath("Desktop")
$startMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "STOA"
$controlUrl = "http://127.0.0.1:18000/control"
$appUrl = "http://127.0.0.1:18000/"

New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null

function New-InternetShortcut {
    param(
        [string]$Path,
        [string]$Url
    )
    $content = "[InternetShortcut]`r`nURL=$Url`r`n"
    Set-Content -Path $Path -Value $content -Encoding ASCII
}

New-InternetShortcut -Path (Join-Path $desktopDir "STOA Control.url") -Url $controlUrl
New-InternetShortcut -Path (Join-Path $desktopDir "STOA.url") -Url $appUrl
New-InternetShortcut -Path (Join-Path $startMenuDir "STOA Control.url") -Url $controlUrl
New-InternetShortcut -Path (Join-Path $startMenuDir "STOA.url") -Url $appUrl

Write-Host "Atalhos web do STOA criados."
