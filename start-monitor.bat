@echo off
title ABM Office Monitor Server
cd /d "%~dp0"
echo ===================================================
echo   ABM Office Command Center - Live Monitor Host
echo ===================================================
curl.exe -s http://localhost:7799/health >nul 2>&1
if not errorlevel 1 (
    echo [OK] Monitor server is already running on port 7799.
    echo Opening Command Center: http://localhost:7799/
    start http://localhost:7799/
) else (
    echo Starting live monitor server on http://localhost:7799 ...
    start "" http://localhost:7799/
    python "%~dp0monitor-server.py"
)
pause
