@echo off
setlocal EnableDelayedExpansion
title Emergency Network Restorer - Tenda AC10 V1.0

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Requesting Administrator privileges to restore network adapter...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ======================================================================
echo    TENDA AC10 V1.0 - EMERGENCY NETWORK RESTORER
echo ======================================================================
echo  Restoring Ethernet adapter to automatic DHCP and DNS...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore_network.ps1"

echo.
echo Press any key to close this window...
pause >nul
