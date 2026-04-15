@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "PYTHONPATH=%PROJECT_ROOT%\.pydeps"
set "PORT=18000"
set "BIND_HOST=127.0.0.1"
set "LOG_PATH=%PROJECT_ROOT%\start-stoa-18000-run.log"

cd /d "%PROJECT_ROOT%"
echo [%date% %time%] Starting STOA on 127.0.0.1:18000>> "%LOG_PATH%"
python app\main.py >> "%LOG_PATH%" 2>&1
