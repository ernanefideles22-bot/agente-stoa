@echo off
setlocal enabledelayedexpansion
title STOA — Iniciando...

set "DIR=%~dp0"
set "LOGDIR=%DIR%logs"
set "PIDFILE=%DIR%.stoa_pids.txt"
set "ENVFILE=%DIR%.env"
set "PYTHON=python"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM ── Verificar .env ──────────────────────────────────────────────────────────
if not exist "%ENVFILE%" (
    echo [ERRO] .env nao encontrado em %DIR%
    echo Execute: copy env.example .env  e configure OPENAI_API_KEY
    pause
    exit /b 1
)

REM ── Gerar STOA_TOKEN se nao existir ─────────────────────────────────────────
findstr /c:"STOA_TOKEN=" "%ENVFILE%" >nul 2>&1
if errorlevel 1 (
    echo [STOA] Gerando token de acesso...
    for /f %%i in ('python -c "import secrets; print(secrets.token_urlsafe(32))"') do set "NEW_TOKEN=%%i"
    echo STOA_TOKEN=!NEW_TOKEN!>> "%ENVFILE%"
    echo [STOA] Token gerado e salvo no .env
)

REM ── Rotar logs antigos (manter 7 dias) ──────────────────────────────────────
python "%DIR%stoa_log_rotate.py" 2>nul

REM ── Matar processos anteriores se existirem ──────────────────────────────────
if exist "%PIDFILE%" (
    echo [STOA] Encerrando sessao anterior...
    for /f "tokens=1,2 delims==" %%a in (%PIDFILE%) do (
        taskkill /PID %%b /F >nul 2>&1
    )
    del "%PIDFILE%"
)

REM ── Iniciar backend ──────────────────────────────────────────────────────────
title STOA — Subindo backend...
echo [STOA] Iniciando backend...
start "STOA-Backend" /min cmd /c "%PYTHON% "%DIR%main.py" >> "%LOGDIR%\backend.log" 2>&1"
timeout /t 3 /nobreak >nul

REM ── Aguardar backend responder ───────────────────────────────────────────────
set "TRIES=0"
:wait_backend
set /a TRIES+=1
if %TRIES% gtr 15 (
    echo [ERRO] Backend nao respondeu em 15 tentativas. Verifique %LOGDIR%\backend.log
    goto :start_agent
)
curl -s -o nul -w "%%{http_code}" http://localhost:8000/api/health 2>nul | findstr "200" >nul
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto :wait_backend
)
echo [STOA] Backend online.

REM ── Iniciar agente Windows ───────────────────────────────────────────────────
:start_agent
echo [STOA] Iniciando agente Windows...
start "STOA-Agent" /min cmd /c "%PYTHON% "%DIR%stoa_device_agent_windows.py" --server http://localhost:8000 >> "%LOGDIR%\agent.log" 2>&1"
timeout /t 2 /nobreak >nul

REM ── Iniciar Cloudflare Tunnel ────────────────────────────────────────────────
where cloudflared >nul 2>&1
if errorlevel 1 (
    echo [AVISO] cloudflared nao encontrado. Acesso externo indisponivel.
    echo         Execute install_cloudflared.bat para instalar.
    goto :save_pids
)
echo [STOA] Iniciando tunel Cloudflare...
start "STOA-Tunnel" /min cmd /c "cloudflared tunnel run stoa >> "%LOGDIR%\tunnel.log" 2>&1"
timeout /t 3 /nobreak >nul

REM ── Salvar PIDs ─────────────────────────────────────────────────────────────
:save_pids
(
    for /f "tokens=2" %%p in ('tasklist /fi "WINDOWTITLE eq STOA-Backend" /fo list 2^>nul ^| findstr "PID:"') do echo backend=%%p
    for /f "tokens=2" %%p in ('tasklist /fi "WINDOWTITLE eq STOA-Agent" /fo list 2^>nul ^| findstr "PID:"') do echo agent=%%p
    for /f "tokens=2" %%p in ('tasklist /fi "WINDOWTITLE eq STOA-Tunnel" /fo list 2^>nul ^| findstr "PID:"') do echo tunnel=%%p
) > "%PIDFILE%"

REM ── Iniciar watchdog ─────────────────────────────────────────────────────────
echo [STOA] Iniciando watchdog...
start "STOA-Watchdog" /min cmd /c "%PYTHON% "%DIR%stoa_watchdog.py" >> "%LOGDIR%\watchdog.log" 2>&1"

REM ── Exibir URL de acesso ─────────────────────────────────────────────────────
echo.
echo ============================================================
echo   STOA esta rodando
echo   Local:   http://localhost:8000
for /f "tokens=*" %%u in ('findstr "PUBLIC_URL=" "%ENVFILE%" 2^>nul') do (
    set "PUB=%%u"
    echo   Externo: !PUB:PUBLIC_URL=!
)
echo   Logs:    %LOGDIR%\
echo ============================================================
echo.
echo Pressione qualquer tecla para fechar esta janela (STOA continua rodando)
pause >nul
