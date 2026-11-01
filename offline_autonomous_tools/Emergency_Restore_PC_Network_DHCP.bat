@echo off
setlocal EnableDelayedExpansion
title Emergency PC Network DHCP & DNS Restorer

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Emergency_Restore_PC_Network_DHCP.ps1" %*
echo.
pause
