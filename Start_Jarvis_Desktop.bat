@echo off
setlocal
title JARVIS - Desktop App
cd /d "%~dp0desktop"

:: The desktop app starts and stops its own backend (it talks to it on http://127.0.0.1:7799/health
:: and signs in with a per-launch token), so no Python window is needed here.

if not exist "..\venv\Scripts\python.exe" (
    echo [ERROR] Python environment not found at %~dp0venv. See README.md "Developer setup".
    pause
    exit /b 1
)
if not exist "node_modules\electron\dist\electron.exe" (
    echo [INFO] Installing desktop app dependencies (first run only)...
    call npm install || (echo [ERROR] npm install failed. Is Node.js installed? & pause & exit /b 1)
)
if not exist "dist\index.html" (
    echo [INFO] Building the app UI (first run only)...
    call npm run build || (echo [ERROR] UI build failed. & pause & exit /b 1)
)

start "" "node_modules\electron\dist\electron.exe" .
exit /b 0
