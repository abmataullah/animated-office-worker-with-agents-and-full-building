@echo off
title Stop ABM Command Center
cd /d "%~dp0"
echo ===================================================
echo   Stopping ABM Command Center ^& Monitor Server
echo ===================================================

:: Stop processes via PowerShell by matching script names
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*desktop-widget.pyw*' -or $_.CommandLine -like '*monitor-server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('Stopped PID ' + $_.ProcessId + ': ' + $_.Name) }"

:: Ensure port 7799 is freed if anything else is holding it
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7799.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [OK] Office desktop widget and monitor server stopped successfully.
timeout /t 2 >nul
