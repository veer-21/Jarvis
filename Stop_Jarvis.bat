@echo off
title JARVIS AI Operating System — Shutdown
echo ======================================================================
echo            Stopping JARVIS AI Operating System...
echo ======================================================================

echo [INFO] Stopping Electron Desktop HUD...
taskkill /F /IM electron.exe >nul 2>&1

echo [INFO] Stopping Python Backend server...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :7799 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
taskkill /F /FI "WINDOWTITLE eq JARVIS Backend*" >nul 2>&1

echo.
echo [SUCCESS] JARVIS processes terminated.
pause
exit /b 0
