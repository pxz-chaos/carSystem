Set-Location $PSScriptRoot
Write-Host "CarFleetSystem V7.2 环境安装脚本" -ForegroundColor Cyan

if (Test-Path "venv") {
    Write-Host "删除旧 venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force venv
}

Write-Host "创建 venv..." -ForegroundColor Cyan
python -m venv venv
if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }

Write-Host "升级 pip..." -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }

Write-Host "清理可能冲突的包..." -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" -m pip uninstall paddleocr paddlex modelscope torch torchvision torchaudio paddlepaddle opencv-python opencv-contrib-python opencv-python-headless numpy -y

Write-Host "安装依赖..." -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }

Write-Host "检查环境..." -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" diagnose_env.py
if ($LASTEXITCODE -ne 0) { throw "环境检查失败" }

Write-Host "环境安装完成。启动请运行 .\run.bat" -ForegroundColor Green
