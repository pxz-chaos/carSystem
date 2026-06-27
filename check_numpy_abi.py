"""Check the NumPy/OpenCV/PaddleOCR ABI combination before starting Flask."""
import importlib
import os
import sys
from pathlib import Path

print("=" * 60)
print("CarFleetSystem NumPy ABI check")
print("=" * 60)
print("Python executable:", sys.executable)
print("Python version:", sys.version.replace("\n", " "))
print("Working dir:", os.getcwd())

errors = []

def show_module(name: str):
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", "unknown")
        path = getattr(mod, "__file__", "built-in")
        print(f"[OK] {name}: {ver}  ({path})")
        return mod
    except Exception as exc:
        msg = f"[FAIL] {name}: {exc}"
        print(msg)
        errors.append(msg)
        return None

np = show_module("numpy")
if np is not None:
    major = int(str(np.__version__).split(".", 1)[0])
    if major >= 2:
        errors.append(
            "NumPy is 2.x, but PaddleOCR 2.7.3 / PaddlePaddle 2.6.2 / OpenCV 4.6.x need NumPy 1.x on this Windows setup. "
            "Run fix_numpy_abi.bat."
        )

show_module("cv2")
show_module("paddle")
show_module("paddleocr")

print("=" * 60)
if errors:
    print("ABI check failed:")
    for e in errors:
        print(" -", e)
    print()
    print("Fix command:")
    print(r"  fix_numpy_abi.bat")
    raise SystemExit(1)

print("ABI check passed.")
