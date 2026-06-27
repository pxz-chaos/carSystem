@echo off
cd /d %~dp0
set OCR_ASCII_HOME=%~d0\CarFleetSystem_OCR_Cache
set HOME=%OCR_ASCII_HOME%
set USERPROFILE=%OCR_ASCII_HOME%
set PADDLEOCR_HOME=%OCR_ASCII_HOME%\.paddleocr
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
set PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
set PIP_DISABLE_PIP_VERSION_CHECK=1

chcp 65001 >nul

echo ========================================
echo Fix PaddleOCR google/protobuf dependency
echo ========================================
echo This fixes:
echo   [FAIL] paddle: No module named 'google'
echo   [FAIL] paddleocr: No module named 'google'
echo.

if not exist venv\Scripts\python.exe (
    echo ERROR: venv\Scripts\python.exe not found. Run setup_env.bat first.
    pause
    exit /b 1
)

echo [1/3] Install protobuf 3.20.2...
venv\Scripts\python.exe -m pip install --no-cache-dir --force-reinstall protobuf==3.20.2 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [2/3] Ensure PaddleOCR packages are present...
venv\Scripts\python.exe -m pip install --no-cache-dir paddlepaddle==2.6.2 paddleocr==2.7.3 --timeout 180 --retries 10
if errorlevel 1 goto fail

echo [3/3] Verify imports...
venv\Scripts\python.exe check_numpy_abi.py
if errorlevel 1 goto fail

echo.
echo ========================================
echo Fixed. Now run run.bat again.
echo ========================================
pause
exit /b 0

:fail
echo.
echo ========================================
echo Fix failed. Copy the error above to ChatGPT.
echo ========================================
pause
exit /b 1
