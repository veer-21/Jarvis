@echo off
setlocal enabledelayedexpansion
title JARVIS AI Operating System — Desktop HUD Launcher

echo ======================================================================
echo          JARVIS AI Operating System — Launching Desktop HUD...
echo ======================================================================
echo.

cd /d "%~dp0"

:: 1. Check if backend port 7799 is already listening
netstat -ano | findstr /R ":7799\>.*LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] JARVIS backend is already running on port 7799.
    goto LAUNCH_DESKTOP
)

:: 2. Verify Python virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at %~dp0venv\Scripts\python.exe.
    pause
    exit /b 1
)

:: 3. Launch Python backend in a new minimized window
echo [INFO] Starting JARVIS backend server...
start "JARVIS Backend" /min "venv\Scripts\python.exe" main.py

:: 4. Poll http://127.0.0.1:7799/health (up to 12 attempts = ~12s)
echo [INFO] Waiting for JARVIS backend to become healthy...
set /a ATTEMPTS=0

:POLL_LOOP
set /a ATTEMPTS+=1
powershell -NoProfile -Command "(Invoke-WebRequest -Uri 'http://127.0.0.1:7799/health' -UseBasicParsing -TimeoutSec 2).StatusCode" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] JARVIS backend is healthy and operational!
    goto LAUNCH_DESKTOP
)

if %ATTEMPTS% GEQ 12 (
    echo [WARNING] Backend is taking longer than usual to respond. Launching Desktop HUD anyway...
    goto LAUNCH_DESKTOP
)

timeout /t 1 /nobreak >nul
goto POLL_LOOP

:LAUNCH_DESKTOP
echo.
echo [INFO] Launching JARVIS Electron Desktop Window...
cd /d "%~dp0desktop"

if exist "node_modules\electron\dist\electron.exe" (
    start "" "node_modules\electron\dist\electron.exe" . --disable-gpu --no-sandbox
) else (
    start "" npx electron . --disable-gpu --no-sandbox
)

echo.
echo ======================================================================
echo  JARVIS Desktop HUD is active. Use Alt+Space to toggle floating HUD!
echo ======================================================================
exit /b 0
