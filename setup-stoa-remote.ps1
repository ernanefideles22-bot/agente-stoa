$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $ScriptDir '.env.safe'
$StoaDir = Join-Path $env:USERPROFILE '.stoa'
$CfExe = $null
$CfLog = Join-Path $env:TEMP 'stoa_cf_tunnel.log'
$SharedSession = 'stoa-shared'
$DefaultPublicBase = 'https://stoa.stoacad.com'
$LocalBase = 'http://127.0.0.1:18000'
$RemoteRoute = '/static/stoa_mobile.html'

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Key
    )

    if (-not (Test-Path $Path)) { return '' }
    $escapedKey = [regex]::Escape($Key)
    $line = Get-Content $Path | Where-Object { $_ -match "^${escapedKey}=(.+)$" } | Select-Object -First 1
    if (-not $line) { return '' }
    return ($line -replace "^${escapedKey}=", '').Trim()
}

function Test-Url {
    param([string]$Url)
    try {
        $null = Invoke-WebRequest -Uri $Url -TimeoutSec 8 -UseBasicParsing
        return $true
    } catch {
        return $false
    }
}

function Ensure-Cloudflared {
    $cmd = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $script:CfExe = $cmd.Source
        return
    }

    if (-not (Test-Path $StoaDir)) {
        New-Item -ItemType Directory -Path $StoaDir | Out-Null
    }

    $localCfExe = Join-Path $StoaDir 'cloudflared.exe'
    if (Test-Path $localCfExe) {
        $script:CfExe = $localCfExe
        return
    }

    Write-Host ""
    Write-Host "  [STOA] cloudflared nao encontrado. Baixando..." -ForegroundColor Cyan
    $cfUrl = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
    Invoke-WebRequest -Uri $cfUrl -OutFile $localCfExe -UseBasicParsing
    $script:CfExe = $localCfExe
    Write-Host "  [STOA] cloudflared instalado em $localCfExe" -ForegroundColor Green
}

function Start-QuickTunnel {
    if (Test-Path $CfLog) { Remove-Item $CfLog -Force }

    Ensure-Cloudflared

    Write-Host ""
    Write-Host "  [STOA] Dominio publico nao respondeu. Abrindo Quick Tunnel..." -ForegroundColor Yellow
    Write-Host "  (aguarde ate 30s para a URL aparecer)" -ForegroundColor Gray
    Write-Host ""

    $cfArgs = "tunnel --url $LocalBase --logfile `"$CfLog`""
    $cfProc = Start-Process -FilePath $CfExe -ArgumentList $cfArgs -NoNewWindow -PassThru

    $tunnelUrl = ''
    $waited = 0
    while ($waited -lt 40 -and -not $tunnelUrl) {
        Start-Sleep -Seconds 1
        $waited++
        if (Test-Path $CfLog) {
            $logContent = Get-Content $CfLog -Raw -ErrorAction SilentlyContinue
            if ($logContent -match 'https://[a-z0-9\-]+\.trycloudflare\.com') {
                $tunnelUrl = $Matches[0]
            }
        }
        Write-Host '  .' -NoNewline
    }
    Write-Host ''

    if (-not $tunnelUrl) {
        if ($cfProc -and -not $cfProc.HasExited) {
            $cfProc | Stop-Process -Force -ErrorAction SilentlyContinue
        }
        throw "Nao foi possivel obter a URL do Quick Tunnel. Verifique o log em $CfLog"
    }

    return @{
        PublicBase = $tunnelUrl
        Process = $cfProc
    }
}

$Token = Get-EnvValue -Path $EnvFile -Key 'STOA_ACCESS_TOKEN'
if (-not $Token) {
    $Token = Read-Host '  Digite o STOA_ACCESS_TOKEN'
}
if (-not $Token) {
    throw 'STOA_ACCESS_TOKEN ausente.'
}

$ConfiguredPublicBase = Get-EnvValue -Path $EnvFile -Key 'STOA_REMOTE_PUBLIC_URL'
if (-not $ConfiguredPublicBase) {
    $ConfiguredPublicBase = $DefaultPublicBase
}
$ConfiguredPublicBase = $ConfiguredPublicBase.TrimEnd('/')

if (-not (Test-Url "$LocalBase/")) {
    Write-Host "  [ERRO] STOA nao respondeu em $LocalBase" -ForegroundColor Red
    Write-Host "  Inicie o backend antes de continuar (run-safe-stoa-local.ps1 ou run-safe-stoa.ps1)" -ForegroundColor Yellow
    exit 1
}

Write-Host "  [STOA] Backend detectado em $LocalBase" -ForegroundColor Green

$PublicBase = $ConfiguredPublicBase
$TunnelProcess = $null

if (Test-Url "$ConfiguredPublicBase$RemoteRoute") {
    Write-Host "  [STOA] Dominio publico detectado em $ConfiguredPublicBase" -ForegroundColor Green
} else {
    $tunnel = Start-QuickTunnel
    $PublicBase = $tunnel.PublicBase.TrimEnd('/')
    $TunnelProcess = $tunnel.Process
}

$MobileLink = "$($PublicBase)$($RemoteRoute)?api=$([uri]::EscapeDataString($PublicBase))&token=$([uri]::EscapeDataString($Token))&session=$SharedSession"
$DesktopLink = "$($LocalBase)$($RemoteRoute)?api=$([uri]::EscapeDataString($PublicBase))&token=$([uri]::EscapeDataString($Token))&session=$SharedSession"

Write-Host ''
Write-Host '  ==============================================' -ForegroundColor Cyan
Write-Host '  STOA MOBILE - ATIVO' -ForegroundColor Cyan
Write-Host '  ==============================================' -ForegroundColor Cyan
Write-Host "  Publico: $PublicBase" -ForegroundColor White
Write-Host "  Sessao:  $SharedSession" -ForegroundColor White
Write-Host '  ----------------------------------------------' -ForegroundColor Cyan
Write-Host "  MOBILE:  $MobileLink" -ForegroundColor Yellow
Write-Host "  DESKTOP: $DesktopLink" -ForegroundColor Green
Write-Host '  ==============================================' -ForegroundColor Cyan
Write-Host ''

Start-Process "msedge.exe" $DesktopLink

try {
    Set-Clipboard -Value $MobileLink
    Write-Host '  Link mobile copiado para a area de transferencia.' -ForegroundColor Green
} catch {
}

if (-not $TunnelProcess) {
    Write-Host ''
    Write-Host '  Dominio estavel em uso. Nenhum tunel temporario foi aberto.' -ForegroundColor Gray
    exit 0
}

Write-Host ''
Write-Host '  Quick Tunnel em uso. Pressione Ctrl+C para encerrar.' -ForegroundColor Gray
Write-Host ''

try {
    while ($true) {
        Start-Sleep -Seconds 10
        if ($TunnelProcess.HasExited) {
            Write-Host '  [AVISO] Quick Tunnel caiu. Reiniciando...' -ForegroundColor Yellow
            $tunnel = Start-QuickTunnel
            $PublicBase = $tunnel.PublicBase.TrimEnd('/')
            $TunnelProcess = $tunnel.Process
        }
    }
} finally {
    if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
        Write-Host '  [STOA] Encerrando Quick Tunnel...' -ForegroundColor Gray
        $TunnelProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}
