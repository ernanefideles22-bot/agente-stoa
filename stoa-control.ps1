$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-StoaScript {
    param(
        [string]$ScriptName,
        [switch]$Wait
    )

    $scriptPath = Join-Path $projectRoot $ScriptName
    if (-not (Test-Path $scriptPath)) {
        throw "Script não encontrado: $scriptPath"
    }

    if ($Wait) {
        return & $scriptPath 2>&1 | Out-String
    }

    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $scriptPath `
        -WindowStyle Hidden | Out-Null
    return "Executado: $ScriptName"
}

function Set-OutputText {
    param([string]$Text)
    $script:outputBox.Text = $Text
}

function Refresh-Status {
    $parts = @()
    $parts += Invoke-StoaScript -ScriptName "status-stoa-supervisor.ps1" -Wait
    $parts += Invoke-StoaScript -ScriptName "status-stoa-daemon.ps1" -Wait
    $parts += Invoke-StoaScript -ScriptName "status-stoa-voice-daemon.ps1" -Wait
    $parts += Invoke-StoaScript -ScriptName "status-stoa-tray.ps1" -Wait
    Set-OutputText (($parts | ForEach-Object { $_.Trim() }) -join [Environment]::NewLine)
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "STOA Control"
$form.Size = New-Object System.Drawing.Size(760, 620)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 32)
$form.ForeColor = [System.Drawing.Color]::White

$title = New-Object System.Windows.Forms.Label
$title.Text = "STOA Control"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(20, 20)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Painel simples para instalar, iniciar e acompanhar o STOA local."
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(22, 55)
$form.Controls.Add($subtitle)

function New-ActionButton {
    param(
        [string]$Text,
        [int]$X,
        [int]$Y,
        [scriptblock]$OnClick
    )
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Size = New-Object System.Drawing.Size(160, 42)
    $button.Location = New-Object System.Drawing.Point($X, $Y)
    $button.BackColor = [System.Drawing.Color]::FromArgb(35, 111, 235)
    $button.ForeColor = [System.Drawing.Color]::White
    $button.FlatStyle = "Flat"
    $button.Add_Click($OnClick)
    $form.Controls.Add($button)
    return $button
}

New-ActionButton -Text "Instalar STOA" -X 20 -Y 95 -OnClick {
    try {
        $result = Invoke-StoaScript -ScriptName "install-stoa.ps1" -Wait
        Set-OutputText $result
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Desinstalar STOA" -X 190 -Y 95 -OnClick {
    try {
        $result = Invoke-StoaScript -ScriptName "uninstall-stoa.ps1" -Wait
        Set-OutputText $result
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Abrir Interface" -X 360 -Y 95 -OnClick {
    Start-Process "http://127.0.0.1:18000" | Out-Null
    Set-OutputText "Interface aberta em http://127.0.0.1:18000"
} | Out-Null

New-ActionButton -Text "Atualizar Status" -X 530 -Y 95 -OnClick {
    try {
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Iniciar Supervisor" -X 20 -Y 150 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "run-stoa-supervisor.ps1" -Wait)
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Parar Supervisor" -X 190 -Y 150 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "stop-stoa-supervisor.ps1" -Wait)
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Iniciar Voz" -X 360 -Y 150 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "run-stoa-voice-daemon.ps1" -Wait)
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Parar Voz" -X 530 -Y 150 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "stop-stoa-voice-daemon.ps1" -Wait)
        Refresh-Status
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Instalar no Logon" -X 20 -Y 205 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "install-stoa-scheduled-task.ps1" -Wait)
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Remover do Logon" -X 190 -Y 205 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "remove-stoa-scheduled-task.ps1" -Wait)
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Atalho Desktop/Menu" -X 360 -Y 205 -OnClick {
    try {
        Set-OutputText (Invoke-StoaScript -ScriptName "install-stoa-control-shortcuts.ps1" -Wait)
    } catch {
        Set-OutputText $_.Exception.Message
    }
} | Out-Null

New-ActionButton -Text "Fechar" -X 530 -Y 205 -OnClick {
    $form.Close()
} | Out-Null

$script:outputBox = New-Object System.Windows.Forms.TextBox
$script:outputBox.Multiline = $true
$script:outputBox.ScrollBars = "Vertical"
$script:outputBox.ReadOnly = $true
$script:outputBox.Size = New-Object System.Drawing.Size(690, 300)
$script:outputBox.Location = New-Object System.Drawing.Point(20, 265)
$script:outputBox.BackColor = [System.Drawing.Color]::FromArgb(11, 18, 32)
$script:outputBox.ForeColor = [System.Drawing.Color]::White
$form.Controls.Add($script:outputBox)

Refresh-Status
[void]$form.ShowDialog()
