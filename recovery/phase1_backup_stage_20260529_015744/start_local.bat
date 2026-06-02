@echo off
REM ============================================================
REM  LOCAL LAPTOP MODE — single-process FastAPI at 127.0.0.1:8080
REM  Production Railway deployment is unchanged; use Railway env there.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set LOCAL_DEV_MODE=1
set LOCAL_ONLY=1
set HOST=127.0.0.1
set PORT=8080
set API_BASE_URL=http://127.0.0.1:8080
set DISABLE_TELEGRAM=1
set DISABLE_TELEGRAM_LISTENER=1
set DISABLE_TELEGRAM_SENDS=1
set DISABLE_RAILWAY_API=1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set TZ=Asia/Kolkata

echo [LOCAL MODE] Starting Trading Copilot on http://127.0.0.1:8080
echo [LOCAL MODE] Telegram listener/sends disabled
echo.

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

mkdir data 2>nul
mkdir logs 2>nul
mkdir config 2>nul

echo Backend: %PYTHON% run_local.py
echo GUI (separate terminal): cd frontend ^&^& set API_BASE_URL=http://127.0.0.1:8080 ^&^& npm start
echo.

%PYTHON% run_local.py
pause
