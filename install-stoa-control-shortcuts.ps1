$ErrorActionPreference = "Stop"

$controlUrl = "http://127.0.0.1:18000/control"
$desktopDir = [Environment]::GetFolderPath("Desktop")
$startMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "STOA"

New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null

$desktopShortcut = Join-Path $desktopDir "STOA Control.lnk"
$menuShortcut = Join-Path $startMenuDir "STOA Control.lnk"

$wsh = New-Object -ComObject WScript.Shell
foreach ($shortcutPath in @($desktopShortcut, $menuShortcut)) {
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "explorer.exe"
    $shortcut.Arguments = $controlUrl
    $shortcut.IconLocation = "explorer.exe,0"
    $shortcut.Save()
}

Write-Host "Atalhos criados:"
Write-Host $desktopShortcut
Write-Host $menuShortcut
