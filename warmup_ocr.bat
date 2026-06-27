@echo off
cd /d %~dp0
set OCR_ASCII_HOME=%~d0\CarFleetSystem_OCR_Cache
set HOME=%OCR_ASCII_HOME%
set USERPROFILE=%OCR_ASCII_HOME%
set PADDLEOCR_HOME=%OCR_ASCII_HOME%\.paddleocr

if not exist venv\Scripts\python.exe (
    echo ERROR: venv\Scripts\python.exe not found.
    echo Please run setup_env.bat first.
    pause
    exit /b 1
)

venv\Scripts\python.exe warmup_ocr.py
pause
