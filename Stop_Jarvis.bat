@echo off
title JARVIS - Stop
echo Stopping JARVIS...

:: Desktop app windows started from THIS folder only (other Electron apps are left alone)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='electron.exe'\" | Where-Object { $_.ExecutablePath -like '%~dp0desktop\*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

:: The JARVIS backend (whatever is listening on its port 7799)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7799 " ^| findstr LISTENING') do (
    taskkill /F /T /PID %%a >nul 2>&1
)
taskkill /F /FI "WINDOWTITLE eq JARVIS Backend*" >nul 2>&1

echo JARVIS stopped.
timeout /t 2 >nul
exit /b 0
