$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Jarvis Local.lnk"
$targetScript = Join-Path $projectRoot "run-jarvis-tray.ps1"

if (-not (Test-Path $targetScript)) {
    throw "Script do tray não encontrado: $targetScript"
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$targetScript`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "powershell.exe,0"
$shortcut.Save()

Write-Host "Atalho de inicialização criado em $shortcutPath"
