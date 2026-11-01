@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - Offline Config ^& WAN MAC Restorer

cd /d "%~dp0"
echo ============================================================================
echo   TENDA AC10 V1.0 - OFFLINE CONFIG ^& WAN MAC RESTORER
echo ============================================================================
echo   Restores Optimized Config (Stock+, stbEn=0, ucloud=0, 8192 NAT)
echo ============================================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Restore_Optimized_Config_and_WAN.ps1" %*

echo.
echo Press any key to close...
pause >nul
