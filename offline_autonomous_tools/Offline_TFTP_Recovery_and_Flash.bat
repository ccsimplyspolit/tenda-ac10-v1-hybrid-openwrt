@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - Autonomous Offline TFTP Recovery & Flash

:: Auto-elevate to Administrator for temporary NIC static IP configuration
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Requesting Administrator privileges for failsafe network configuration...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
echo ============================================================================
echo   TENDA AC10 V1.0 - 100%% OFFLINE AUTONOMOUS TFTP RECOVERY ^& FLASHER
echo ============================================================================
echo   1. Plug Ethernet cable into LAN1, LAN2, or LAN3 (NOT WAN - Port 3 is off)
echo   2. Hold RST button while powering on for 8-15 seconds
echo   3. Adapter will automatically return to DHCP/DNS in the finally block!
echo ============================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Offline_TFTP_Recovery_and_Flash.ps1" %*

echo.
echo Press any key to close...
pause >nul
