@echo off
cd /d %~dp0
set OCR_ASCII_HOME=%~d0\CarFleetSystem_OCR_Cache
set HOME=%OCR_ASCII_HOME%
set USERPROFILE=%OCR_ASCII_HOME%
set PADDLEOCR_HOME=%OCR_ASCII_HOME%\.paddleocr
chcp 65001 >nul

if not exist venv\Scripts\python.exe (
    echo ERROR: venv\Scripts\python.exe not found.
    echo Please run setup_env.bat first.
    pause
    exit /b 1
)

venv\Scripts\python.exe check_numpy_abi.py
if errorlevel 1 (
    echo Please run fix_numpy_abi.bat.
    pause
    exit /b 1
)
venv\Scripts\python.exe diagnose_env.py

pause
