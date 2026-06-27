import os
from pathlib import Path

project = Path(__file__).resolve().parent

def is_ascii(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except Exception:
        return False

# Batch scripts set OCR_ASCII_HOME to e.g. D:\CarFleetSystem_OCR_Cache.
# Keep a Python fallback for users who run this file manually.
env_home = os.environ.get("OCR_ASCII_HOME")
if env_home:
    local_home = Path(env_home)
else:
    drive = project.drive or "C:"
    local_home = Path(drive + "\\CarFleetSystem_OCR_Cache") if os.name == "nt" else Path("/tmp/CarFleetSystem_OCR_Cache")

local_home.mkdir(parents=True, exist_ok=True)
os.environ["OCR_ASCII_HOME"] = str(local_home)
os.environ["HOME"] = str(local_home)
os.environ["USERPROFILE"] = str(local_home)
os.environ["PADDLEOCR_HOME"] = str(local_home / ".paddleocr")

print("=== CarFleetSystem V8.3 OCR Warmup ===")
print("Project:", project)
print("Project path is ASCII:", is_ascii(project))
print("OCR ASCII HOME:", local_home)
print("OCR HOME is ASCII:", is_ascii(local_home))
print("Expected PaddleOCR cache:", local_home / ".paddleocr")

from utils.ocr_utils import get_paddle_ocr, _configure_ocr_environment

actual_home = Path(_configure_ocr_environment())
print("Actual OCR HOME:", actual_home)
print("Actual OCR HOME is ASCII:", is_ascii(actual_home))

ocr = get_paddle_ocr()
print("PaddleOCR loaded:", type(ocr))

model_files = list((actual_home / ".paddleocr").rglob("inference.pdmodel"))
print("Found inference.pdmodel files:", len(model_files))
for p in model_files:
    print("FOUND:", p)

if not model_files:
    raise RuntimeError("No inference.pdmodel found in ASCII OCR cache. Please rerun warmup_ocr.bat or check network.")

print("Warmup finished.")
