@echo off
setlocal enabledelayedexpansion
title STOA - Registro no Task Scheduler

set "DIR=%~dp0"
set "BAT=%DIR%start_stoa.bat"
set "TASKNAME=STOA-Autostart"

echo.
echo ============================================================
echo   STOA - Configurar inicializacao automatica com Windows
echo ============================================================
echo.

REM Verificar se ja existe
schtasks /query /tn "%TASKNAME%" >nul 2>&1
if not errorlevel 1 (
    echo Tarefa ja existe. Recriando...
    schtasks /delete /tn "%TASKNAME%" /f >nul
)

REM Criar tarefa que roda no login do usuario atual
schtasks /create ^
    /tn "%TASKNAME%" ^
    /tr "\"%BAT%\"" ^
    /sc ONLOGON ^
    /rl HIGHEST ^
    /delay 0000:30 ^
    /f

if errorlevel 1 (
    echo [ERRO] Falha ao registrar tarefa. Rode este script como Administrador.
    pause & exit /b 1
)

echo.
echo [OK] STOA vai iniciar automaticamente apos o login do Windows.
echo      Para remover: schtasks /delete /tn "%TASKNAME%" /f
echo.
pause
