@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - Restore Factory Stock Firmware

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Administrator privileges required to manage network adapter.
    echo [!] Requesting elevation...
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ======================================================================
echo    RESTORING FACTORY STOCK FIRMWARE (Tenda_AC10_V1_Stock_TFTP_Recovery.bin)
echo ======================================================================
echo  Restoring clean factory stock Linux 3.10.90 + SquashFS.
echo.

python "%~dp0flash_firmware.py" --stock

echo.
echo Press any key to exit...
pause >nul
