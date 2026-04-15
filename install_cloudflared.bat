@echo off
setlocal enabledelayedexpansion
title STOA - Setup Cloudflare Tunnel

set "DIR=%~dp0"
set "CF_BIN=%DIR%cloudflared.exe"
set "CF_URL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

echo.
echo ============================================================
echo   STOA - Instalacao do Cloudflare Tunnel
echo ============================================================
echo.

REM ── Baixar cloudflared se nao existir ────────────────────────────────────────
if not exist "%CF_BIN%" (
    echo [1/4] Baixando cloudflared...
    curl -L -o "%CF_BIN%" "%CF_URL%"
    if errorlevel 1 (
        echo [ERRO] Falha ao baixar cloudflared. Verifique sua conexao.
        pause & exit /b 1
    )
    echo [OK] cloudflared baixado.
) else (
    echo [1/4] cloudflared ja existe.
)

REM ── Login no Cloudflare ───────────────────────────────────────────────────────
echo.
echo [2/4] Fazendo login no Cloudflare...
echo       Uma aba do navegador vai abrir. Autorize o dominio que voce quer usar.
echo       Se ja estiver logado, pressione qualquer tecla para pular.
pause
"%CF_BIN%" login

REM ── Criar tunnel ─────────────────────────────────────────────────────────────
echo.
echo [3/4] Criando tunnel "stoa"...
"%CF_BIN%" tunnel create stoa

REM ── Criar config do tunnel ───────────────────────────────────────────────────
echo.
echo [4/4] Configurando roteamento...

if not exist "%USERPROFILE%\.cloudflared" mkdir "%USERPROFILE%\.cloudflared"

REM Descobrir UUID do tunnel criado
for /f "tokens=*" %%i in ('"%CF_BIN%" tunnel list --name stoa --output json 2^>nul') do set "TUNNEL_JSON=%%i"

echo.
echo ============================================================
echo   Proximo passo manual:
echo.
echo   1. Acesse https://dash.cloudflare.com
echo   2. Va em Zero Trust > Networks > Tunnels > stoa
echo   3. Adicione uma Public Hostname apontando para:
echo      Service: http://localhost:8000
echo   4. Anote a URL gerada (ex: stoa.seudominio.com)
echo   5. Adicione no .env:
echo      PUBLIC_URL=https://stoa.seudominio.com
echo.
echo   Ou use um tunnel temporario agora para testar:
echo      cloudflared tunnel --url http://localhost:8000
echo ============================================================
echo.
pause
