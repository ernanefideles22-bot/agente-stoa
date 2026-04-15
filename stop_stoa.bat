@echo off
title STOA - Encerrando
set "DIR=%~dp0"
set "PIDFILE=%DIR%.stoa_pids.txt"

echo [STOA] Encerrando todos os processos...

if exist "%PIDFILE%" (
    for /f "tokens=1,2 delims==" %%a in (%PIDFILE%) do (
        taskkill /PID %%b /F >nul 2>&1
    )
    del "%PIDFILE%"
)

taskkill /IM cloudflared.exe /F >nul 2>&1

echo [STOA] Encerrado.
timeout /t 2 /nobreak >nul
