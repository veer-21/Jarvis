@echo off
setlocal enabledelayedexpansion
title JARVIS AI Operating System — Consumer Web Launcher

echo ======================================================================
echo             JARVIS AI Operating System (v3.0) — Launching...
echo ======================================================================
echo.

cd /d "%~dp0"

:: 1. Check if port 7799 is already listening
netstat -ano | findstr /R ":7799\>.*LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] JARVIS backend is already running on port 7799.
    goto OPEN_BROWSER
)

:: 2. Verify Python virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at %~dp0venv\Scripts\python.exe.
    echo Please configure the environment or run python -m venv venv first.
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
    goto OPEN_BROWSER
)

if %ATTEMPTS% GEQ 12 (
    echo [WARNING] Backend is taking longer than usual to respond. Opening browser anyway...
    goto OPEN_BROWSER
)

timeout /t 1 /nobreak >nul
goto POLL_LOOP

:OPEN_BROWSER
echo.
echo [INFO] Opening JARVIS Mission Control in your default browser...
start http://127.0.0.1:7799
echo.
echo ======================================================================
echo  JARVIS is online. Keep this window or the minimized backend open.
echo ======================================================================
exit /b 0
