@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - OpenWrt ISP WAN ^& Wi-Fi Configurator

cd /d "%~dp0"
echo ============================================================================
echo   TENDA AC10 V1.0 - OPENWRT ISP WAN ^& WI-FI CONFIGURATOR
echo ============================================================================
echo   Configures ISP Cloned WAN MAC (eth0.1) ^& Wi-Fi SSIDs/Keys via SSH.
echo   Target OpenWrt: 192.168.0.1 (root@192.168.0.1)
echo ============================================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Configure_OpenWrt_ISP_WAN_and_WiFi.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% neq 0 (
    echo.
    echo ============================================================================
    echo   [ERROR] OpenWrt configuration failed with exit code %EXIT_CODE%.
    echo ============================================================================
) else (
    echo.
    echo ============================================================================
    echo   [SUCCESS] OpenWrt ISP WAN MAC ^& Wi-Fi configuration complete.
    echo ============================================================================
)

echo.
echo Press any key to close...
pause >nul
exit /b %EXIT_CODE%
