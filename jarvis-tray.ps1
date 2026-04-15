$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-ProjectScript {
    param([string]$ScriptName)

    $scriptPath = Join-Path $projectRoot $ScriptName
    if (-not (Test-Path $scriptPath)) {
        [System.Windows.Forms.MessageBox]::Show("Script não encontrado: $scriptPath")
        return
    }

    Start-Process `
        -FilePath "powershell" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath `
        -WindowStyle Hidden | Out-Null
}

function Show-Status {
    $apiStatus = & (Join-Path $projectRoot "status-jarvis-daemon.ps1") 2>&1 | Out-String
    $voiceStatus = & (Join-Path $projectRoot "status-jarvis-voice-daemon.ps1") 2>&1 | Out-String
    [System.Windows.Forms.MessageBox]::Show(($apiStatus.Trim() + [Environment]::NewLine + $voiceStatus.Trim()), "Jarvis Status") | Out-Null
}

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = [System.Drawing.SystemIcons]::Application
$notifyIcon.Text = "Jarvis Local"
$notifyIcon.Visible = $true

$contextMenu = New-Object System.Windows.Forms.ContextMenuStrip

$openUiItem = $contextMenu.Items.Add("Abrir Interface")
$openUiItem.Add_Click({
    Start-Process "http://127.0.0.1:18000" | Out-Null
})

$statusItem = $contextMenu.Items.Add("Status")
$statusItem.Add_Click({
    Show-Status
})

$contextMenu.Items.Add("-") | Out-Null

$startApiItem = $contextMenu.Items.Add("Iniciar API")
$startApiItem.Add_Click({
    Invoke-ProjectScript -ScriptName "run-jarvis-daemon.ps1"
})

$stopApiItem = $contextMenu.Items.Add("Parar API")
$stopApiItem.Add_Click({
    Invoke-ProjectScript -ScriptName "stop-jarvis-daemon.ps1"
})

$startVoiceItem = $contextMenu.Items.Add("Iniciar Voz")
$startVoiceItem.Add_Click({
    Invoke-ProjectScript -ScriptName "run-jarvis-voice-daemon.ps1"
})

$stopVoiceItem = $contextMenu.Items.Add("Parar Voz")
$stopVoiceItem.Add_Click({
    Invoke-ProjectScript -ScriptName "stop-jarvis-voice-daemon.ps1"
})

$contextMenu.Items.Add("-") | Out-Null

$quitItem = $contextMenu.Items.Add("Sair")
$quitItem.Add_Click({
    $notifyIcon.Visible = $false
    $notifyIcon.Dispose()
    [System.Windows.Forms.Application]::Exit()
})

$notifyIcon.ContextMenuStrip = $contextMenu
$notifyIcon.Add_DoubleClick({
    Start-Process "http://127.0.0.1:18000" | Out-Null
})

$notifyIcon.ShowBalloonTip(3000, "Jarvis Local", "Tray residente carregado.", [System.Windows.Forms.ToolTipIcon]::Info)
[System.Windows.Forms.Application]::Run()
