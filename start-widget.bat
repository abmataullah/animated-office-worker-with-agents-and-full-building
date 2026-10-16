@echo off
title ABM Command Center
cd /d "%~dp0"

:: Start monitor server if not running
curl.exe -s http://localhost:7799/health >nul 2>&1
if errorlevel 1 (
    echo Starting monitor server on port 7799...
    start /B pythonw "%~dp0monitor-server.py"
    timeout /t 2 /nointerrupt >nul
)

:: Launch desktop widget window
echo Launching ABM Command Center widget window...
start /B pythonw "%~dp0desktop-widget.pyw"

:: Open in browser for instant access
echo Opening in default browser (http://localhost:7799/)...
start http://localhost:7799/
