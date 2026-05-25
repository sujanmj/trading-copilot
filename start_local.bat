@echo off
REM ============================================================
REM  OPTIONAL — local Windows dev only. Production uses Railway.
REM  Double-click only when testing locally against localhost API.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set PORT=8000
set HOST=127.0.0.1
set API_BASE_URL=http://localhost:8000
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo [OPTIONAL LOCAL DEV] Not required for Railway deployment.
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

start "Copilot-Backend-Local" cmd /k "set PYTHONPATH=.&& %PYTHON% -m backend.api_server"
timeout /t 5 /nobreak >nul
where npm >nul 2>&1 && start "Copilot-GUI" cmd /k "set API_BASE_URL=http://localhost:8000&& npm start"
echo Local dev started. Set API_BASE_URL=http://localhost:8000 in config\keys.env for GUI.
pause
