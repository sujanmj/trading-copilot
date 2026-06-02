@echo off
REM ============================================================
REM  OPTIONAL — local Windows dev only. Production uses Railway.
REM  Double-click only when testing locally against localhost API.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set PORT=8080
set HOST=127.0.0.1
set API_BASE_URL=http://localhost:8080
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

echo Preferred: python run_local.py
echo With forced EOD test: set LOCAL_FORCE_EOD=1 ^&^& python run_local.py
echo.
echo Legacy split mode: uvicorn + npm in separate windows below...
start "Copilot-Backend-Local" cmd /k "set TZ=Asia/Kolkata&& %PYTHON% -m uvicorn backend.api.api_server:app --host 127.0.0.1 --port %PORT%"
timeout /t 5 /nobreak >nul
where npm >nul 2>&1 && start "Copilot-GUI" cmd /k "cd /d %~dp0frontend&& set API_BASE_URL=http://localhost:8080&& npm start"
echo Local dev started. Set API_BASE_URL=http://localhost:8080 in config\keys.env for GUI.
pause
