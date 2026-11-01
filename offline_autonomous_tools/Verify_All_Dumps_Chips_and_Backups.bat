@echo off
setlocal EnableDelayedExpansion
title Tenda AC10 V1.0 - Offline Forensic Verifier (Dumps, Chips & Backups)

cd /d "%~dp0"
python "%~dp0Verify_All_Dumps_Chips_and_Backups.py"
echo.
pause
