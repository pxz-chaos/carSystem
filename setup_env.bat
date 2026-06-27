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
echo CarFleetSystem Environment Setup
echo ========================================
echo This will recreate venv and install all required packages.
echo.
pause

if exist venv (
    echo [1/10] Remove old venv completely...
    rmdir /s /q venv
) else (
    echo [1/10] No old venv found.
)

echo [2/10] Create clean venv...
python -m venv venv
if errorlevel 1 goto fail

echo [3/10] Upgrade pip/setuptools/wheel...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [4/10] Remove conflicting packages if any...
venv\Scripts\python.exe -m pip uninstall -y paddleocr paddlex modelscope torch torchvision torchaudio paddlepaddle opencv-python opencv-contrib-python opencv-python-headless numpy Pillow pillow protobuf

echo [5/10] Install NumPy/Pillow/protobuf lock...
venv\Scripts\python.exe -m pip install --no-cache-dir numpy==1.26.4 Pillow==10.4.0 protobuf==3.20.2 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [6/10] Install OpenCV contrib without changing NumPy...
venv\Scripts\python.exe -m pip install --no-cache-dir --no-deps opencv-contrib-python==4.6.0.66 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [7/10] Install web/report/SMS packages...
venv\Scripts\python.exe -m pip install --no-cache-dir flask==3.0.3 werkzeug==3.0.3 gunicorn==22.0.0 pandas==2.2.2 openpyxl==3.1.5 alibabacloud_dysmsapi20170525==3.1.2 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [8/10] Install PaddleOCR packages...
venv\Scripts\python.exe -m pip install --no-cache-dir paddlepaddle==2.6.2 paddleocr==2.7.3 --timeout 180 --retries 10
if errorlevel 1 goto fail

echo [9/10] Final ABI lock: NumPy 1.26.4, protobuf 3.20.2, and single OpenCV package...
venv\Scripts\python.exe -m pip uninstall -y opencv-python opencv-python-headless
venv\Scripts\python.exe -m pip install --no-cache-dir --force-reinstall --no-deps numpy==1.26.4 protobuf==3.20.2 opencv-contrib-python==4.6.0.66 --timeout 120 --retries 10
if errorlevel 1 goto fail

echo [10/10] Verify environment...
venv\Scripts\python.exe check_numpy_abi.py
if errorlevel 1 goto fail
venv\Scripts\python.exe diagnose_env.py
if errorlevel 1 goto fail
venv\Scripts\python.exe warmup_ocr.py
if errorlevel 1 goto fail

echo.
echo ========================================
echo Environment setup finished. Start with run.bat.
echo ========================================
pause
exit /b 0

:fail
echo.
echo ========================================
echo Environment setup failed. Copy the error above to ChatGPT.
echo ========================================
pause
exit /b 1
