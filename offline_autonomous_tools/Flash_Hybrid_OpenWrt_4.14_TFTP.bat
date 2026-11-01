@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - 1-Click Flash Hybrid OpenWrt 4.14 (TFTP)

:: Auto-elevate to Administrator for temporary NIC static IP configuration
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Requesting Administrator privileges for failsafe network configuration...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"

set "FW_PATH="
if not "%~1"=="" (
    if exist "%~1" (
        set "FW_PATH=%~f1"
    )
)

if not defined FW_PATH (
    if exist "%SCRIPT_DIR%..\02_Compiled_Hybrid_OpenWrt_4.14_Firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin" (
        set "FW_PATH=%SCRIPT_DIR%..\02_Compiled_Hybrid_OpenWrt_4.14_Firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin"
    ) else if exist "%SCRIPT_DIR%..\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin" (
        set "FW_PATH=%SCRIPT_DIR%..\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin"
    ) else if exist "%SCRIPT_DIR%tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin" (
        set "FW_PATH=%SCRIPT_DIR%tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin"
    ) else if exist "%SCRIPT_DIR%..\firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin" (
        set "FW_PATH=%SCRIPT_DIR%..\firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin"
    )
)

if not defined FW_PATH (
    echo ============================================================================
    echo   [ERROR] Firmware binary 'tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin' not found!
    echo ============================================================================
    echo Searched locations:
    echo   1. Command-line argument: "%~1"
    echo   2. %SCRIPT_DIR%..\02_Compiled_Hybrid_OpenWrt_4.14_Firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
    echo   3. %SCRIPT_DIR%..\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
    echo   4. %SCRIPT_DIR%tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
    echo   5. %SCRIPT_DIR%..\firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
    echo.
    echo Please place 'tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin' into one of these paths
    echo or specify its location as argument: %~nx0 ^<path_to_factory.bin^>
    echo ============================================================================
    pause
    exit /b 1
)

echo ============================================================================
echo   TENDA AC10 V1.0 - 1-CLICK HYBRID OPENWRT 4.14 TFTP FLASHER
echo   Target Image: !FW_PATH! (cs6c @ 0x30000)
echo ============================================================================
echo   1. Plug Ethernet cable into LAN1, LAN2, or LAN3 (NOT WAN - Port 3 is off)
echo   2. Hold RST button (GPIO 54) while powering on for 8-15 seconds
echo   3. Adapter will automatically return to DHCP/DNS in the finally block!
echo   4. After reboot (~90s), run Configure_OpenWrt_ISP_WAN_and_WiFi.bat!
echo   5. OpenWrt LuCI Web UI opens at http://192.168.0.1
echo ============================================================================
echo.

set "EXTRA_ARGS="
:collect_args
if "%~1"=="" goto run_flasher
if "%~f1"=="!FW_PATH!" (
    shift /1
    goto collect_args
)
set EXTRA_ARGS=!EXTRA_ARGS! %1
shift /1
goto collect_args

:run_flasher
if exist "%SCRIPT_DIR%Offline_TFTP_Recovery_and_Flash.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%Offline_TFTP_Recovery_and_Flash.ps1" -FirmwarePath "!FW_PATH!" !EXTRA_ARGS!
) else if exist "%SCRIPT_DIR%..\offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%..\offline_autonomous_tools\Offline_TFTP_Recovery_and_Flash.ps1" -FirmwarePath "!FW_PATH!" !EXTRA_ARGS!
) else if exist "%SCRIPT_DIR%flash_firmware.py" (
    python "%SCRIPT_DIR%flash_firmware.py" --firmware "!FW_PATH!" !EXTRA_ARGS!
) else (
    echo [ERROR] Flasher engine script not found in %SCRIPT_DIR%!
    exit /b 1
)
set "FLASH_EXIT=%ERRORLEVEL%"

if %FLASH_EXIT% equ 0 (
    echo.
    echo ============================================================================
    echo   [SUCCESS] TFTP FLASH COMPLETED SUCCESSFULLY!
    echo ============================================================================
    echo   NEXT STEPS:
    echo   1. Wait ~90-120 seconds for Hybrid OpenWrt 4.14 to complete first boot.
    echo   2. Plug your ISP internet cable into the WAN port (blue port).
    echo   3. Run 'Configure_OpenWrt_ISP_WAN_and_WiFi.bat' to autonomously clone
    echo      your ISP WAN MAC and configure Wi-Fi SSIDs ^& passwords.
    echo   4. Access OpenWrt LuCI Web UI at: http://192.168.0.1
    echo ============================================================================
) else (
    echo.
    echo ============================================================================
    echo   [ERROR] TFTP Flash failed with exit code %FLASH_EXIT%.
    echo   If network adapter was not restored, run Emergency_Restore_PC_Network_DHCP.bat
    echo ============================================================================
)

echo.
echo Press any key to close...
pause >nul
exit /b %FLASH_EXIT%
