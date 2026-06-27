@echo off
chcp 65001 >nul
cd /d %~dp0
set OCR_ASCII_HOME=%~d0\CarFleetSystem_OCR_Cache
set HOME=%OCR_ASCII_HOME%
set USERPROFILE=%OCR_ASCII_HOME%
set PADDLEOCR_HOME=%OCR_ASCII_HOME%\.paddleocr
set OCR_DEBUG_ALWAYS=1
set OCR_DEBUG_CROPS=1

if not exist venv\Scripts\python.exe (
    echo ERROR: venv\Scripts\python.exe not found.
    echo Please run setup_env.bat first.
    pause
    exit /b 1
)

echo Checking NumPy ABI...
venv\Scripts\python.exe check_numpy_abi.py
if errorlevel 1 (
    echo.
    echo Please close this window, run fix_numpy_abi.bat, then run run.bat again.
    pause
    exit /b 1
)

venv\Scripts\python.exe app.py
pause
