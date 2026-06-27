@echo off
chcp 65001 >nul
cd /d %~dp0
set OCR_ASCII_HOME=%~d0\CarFleetSystem_OCR_Cache
set HOME=%OCR_ASCII_HOME%
set USERPROFILE=%OCR_ASCII_HOME%
set PADDLEOCR_HOME=%OCR_ASCII_HOME%\.paddleocr
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
set PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
set PIP_DISABLE_PIP_VERSION_CHECK=1

echo ========================================
echo Repair Python/OCR environment
echo ========================================
echo This repairs NumPy/OpenCV/PaddleOCR dependencies.
echo.

if not exist venv\Scripts\python.exe (
    echo ERROR: venv\Scripts\python.exe not found. Run setup_env.bat first.
    pause
    exit /b 1
)

echo [1/7] Upgrade pip/setuptools/wheel...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [2/7] Remove conflicting OpenCV packages...
venv\Scripts\python.exe -m pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python

echo [3/7] Install NumPy/Pillow/protobuf lock...
venv\Scripts\python.exe -m pip install --no-cache-dir --force-reinstall --no-deps numpy==1.26.4 Pillow==10.4.0 protobuf==3.20.2 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [4/7] Install OpenCV contrib without changing NumPy...
venv\Scripts\python.exe -m pip install --no-cache-dir --force-reinstall --no-deps opencv-contrib-python==4.6.0.66 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [5/7] Install/repair PaddleOCR packages...
venv\Scripts\python.exe -m pip install --no-cache-dir paddlepaddle==2.6.2 paddleocr==2.7.3 --timeout 180 --retries 10
if errorlevel 1 goto fail

echo [6/7] Final dependency lock...
venv\Scripts\python.exe -m pip uninstall -y opencv-python opencv-python-headless
venv\Scripts\python.exe -m pip install --no-cache-dir --force-reinstall --no-deps numpy==1.26.4 protobuf==3.20.2 opencv-contrib-python==4.6.0.66 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [7/7] Verify imports and warm up OCR...
venv\Scripts\python.exe check_numpy_abi.py
if errorlevel 1 goto fail
venv\Scripts\python.exe warmup_ocr.py
if errorlevel 1 goto fail

echo.
echo ========================================
echo Repair finished. Now run run.bat again.
echo ========================================
pause
exit /b 0

:fail
echo.
echo ========================================
echo Environment repair failed. Copy the error above to ChatGPT.
echo ========================================
pause
exit /b 1
