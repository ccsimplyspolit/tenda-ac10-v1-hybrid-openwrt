@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - Autonomous Emergency Recovery Suite

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Administrator privileges required to manage network adapter during recovery.
    echo [!] Requesting elevation...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\" %*' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ======================================================================
echo    TENDA AC10 V1.0 - 100%% AUTONOMOUS OFFLINE RECOVERY SUITE
echo ======================================================================
echo  Zero external dependencies. Works completely without internet.
echo.

python "%~dp0flash_firmware.py" %*

echo.
echo Press any key to exit...
pause >nul
