import importlib
import os
import subprocess
import sys
from pathlib import Path

print("=" * 60)
print("CarFleetSystem V7.7 环境诊断")
print("=" * 60)
print("Python executable:", sys.executable)
print("Python version:", sys.version.replace("\n", " "))
print("Working dir:", os.getcwd())
print("OCR_ASCII_HOME:", os.environ.get("OCR_ASCII_HOME", ""))
print("HOME:", os.environ.get("HOME", ""))
print("USERPROFILE:", os.environ.get("USERPROFILE", ""))
print("PADDLEOCR_HOME:", os.environ.get("PADDLEOCR_HOME", ""))
print()

required = [
    "flask",
    "werkzeug",
    "pandas",
    "openpyxl",
    "numpy",
    "cv2",
    "paddle",
    "paddleocr",
]

ok = True
for name in required:
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", "unknown")
        print(f"[OK] {name}: {ver}")
        if name == "numpy":
            try:
                major = int(str(ver).split(".", 1)[0])
                if major >= 2:
                    ok = False
                    print("[FAIL] numpy: 当前是 NumPy 2.x，会导致 PaddleOCR/OpenCV ABI 错误。请运行 fix_numpy_abi.bat。")
            except Exception:
                pass
    except Exception as exc:
        ok = False
        print(f"[FAIL] {name}: {exc}")

print()
try:
    out = subprocess.check_output([sys.executable, "-m", "pip", "--version"], text=True, encoding="utf-8", errors="ignore")
    print("pip:", out.strip())
except Exception as exc:
    ok = False
    print("pip check failed:", exc)

print()
try:
    from utils.ocr_utils import _configure_ocr_environment, _has_paddle_model_files, _is_ascii_path
    ocr_home = Path(_configure_ocr_environment())
    print("Resolved OCR HOME:", ocr_home)
    print("Resolved OCR HOME is ASCII:", _is_ascii_path(str(ocr_home)))
    print("Paddle model files found:", _has_paddle_model_files(str(ocr_home / ".paddleocr")))
except Exception as exc:
    print("OCR path check failed:", exc)

print("=" * 60)
if not ok:
    print("环境检查失败。请确认你启动 app.py 时使用的是上面显示的 venv\\Scripts\\python.exe。")
    raise SystemExit(1)
print("全部依赖正常，可以运行：venv\\Scripts\\python.exe app.py")
