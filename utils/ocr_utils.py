"""
CarFleetSystem V8.8 OCR module - Fuzzy Total Mileage

目标：
1. 使用 PaddleOCR 作为主识别引擎；
2. 使用 OpenCV 做车牌黄色区域检测、仪表区域 ROI 裁剪、轻量增强；
3. 使用业务规则识别“总里程”，避免把本次行驶、累计行驶、续航、电量、时间误当作总里程；
4. 车牌识别支持中文省份识别失败时，按 DEFAULT_PLATE_PROVINCE 自动补齐，例如 ADL6725 -> 贵ADL6725；
5. OCR 模型全局单例缓存，避免每次上传都重新加载；
6. V8.6：先快后准，低里程候选更严格；自动识别结果只作为确认页预填建议；
7. V8.8：总里程标签采用模糊识别，不再只依赖“总里程/总里理”固定文字。
"""

import os
import re
import uuid
import tempfile
import shutil
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None

try:
    from config import OCR_CONFIDENCE_THRESHOLD  # type: ignore
except Exception:
    OCR_CONFIDENCE_THRESHOLD = 0.50

try:
    from config import DEFAULT_PLATE_PROVINCE  # type: ignore
except Exception:
    DEFAULT_PLATE_PROVINCE = os.environ.get("DEFAULT_PLATE_PROVINCE", "贵")

try:
    from config import OCR_DEBUG_CROPS  # type: ignore
except Exception:
    OCR_DEBUG_CROPS = os.environ.get("OCR_DEBUG_CROPS", "0") == "1"

# V7.1: 无论是否开启裁剪图调试，都写入 debug_ocr/last_ocr.txt，便于定位为什么识别失败。
OCR_DEBUG_ALWAYS = os.environ.get("OCR_DEBUG_ALWAYS", "1") == "1"

try:
    from config import OCR_USE_GPU  # type: ignore
except Exception:
    OCR_USE_GPU = os.environ.get("OCR_USE_GPU", "0") == "1"

try:
    from config import OCR_MAX_IMAGE_WIDTH  # type: ignore
except Exception:
    OCR_MAX_IMAGE_WIDTH = int(os.environ.get("OCR_MAX_IMAGE_WIDTH", "1100"))

try:
    from config import OCR_FAST_MODE  # type: ignore
except Exception:
    OCR_FAST_MODE = os.environ.get("OCR_FAST_MODE", "1") == "1"

try:
    from config import OCR_FALLBACK_ENABLED  # type: ignore
except Exception:
    OCR_FALLBACK_ENABLED = os.environ.get("OCR_FALLBACK_ENABLED", "0") == "1"

try:
    from config import OCR_EARLY_STOP  # type: ignore
except Exception:
    OCR_EARLY_STOP = os.environ.get("OCR_EARLY_STOP", "1") == "1"

try:
    from config import OCR_USE_ANGLE_CLS  # type: ignore
except Exception:
    OCR_USE_ANGLE_CLS = os.environ.get("OCR_USE_ANGLE_CLS", "0") == "1"

try:
    from config import OCR_CPU_THREADS  # type: ignore
except Exception:
    OCR_CPU_THREADS = int(os.environ.get("OCR_CPU_THREADS", "4"))

try:
    from config import OCR_DET_LIMIT_SIDE_LEN  # type: ignore
except Exception:
    OCR_DET_LIMIT_SIDE_LEN = int(os.environ.get("OCR_DET_LIMIT_SIDE_LEN", "960"))

try:
    from config import OCR_MAX_ROI_IMAGES  # type: ignore
except Exception:
    OCR_MAX_ROI_IMAGES = int(os.environ.get("OCR_MAX_ROI_IMAGES", "5"))

try:
    from config import OCR_MIN_AUTO_MILEAGE  # type: ignore
except Exception:
    OCR_MIN_AUTO_MILEAGE = int(os.environ.get("OCR_MIN_AUTO_MILEAGE", "1000"))


# =========================================================
# Windows/PaddleOCR 路径修复
# =========================================================

_OCR_ASCII_HOME: Optional[str] = None


def _is_ascii_path(path: str) -> bool:
    """Paddle 的 C++ 推理层在 Windows 上经常无法读取中文路径。"""
    try:
        str(path).encode("ascii")
        return True
    except Exception:
        return False


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _can_use_dir(path: str) -> bool:
    """目录必须是 ASCII 路径并且当前用户可写。"""
    if not path or not _is_ascii_path(path):
        return False
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def _choose_ascii_ocr_home() -> str:
    """
    选择一个不含中文/空格问题较少的 OCR 工作目录。

    注意：只把模型放到 project\\ocr_user_home 仍不够；如果项目在
    D:\\网页下载\\... 这种中文路径下，Paddle 仍可能报 Cannot open file。
    所以优先使用盘符根目录下的 CarFleetSystem_OCR_Cache。
    """
    project = _project_root()
    candidates: List[str] = []

    env_home = os.environ.get("OCR_ASCII_HOME")
    if env_home:
        candidates.append(env_home)

    # Windows: 与项目同盘，如 D:\CarFleetSystem_OCR_Cache
    drive, _ = os.path.splitdrive(project)
    if drive:
        candidates.append(os.path.join(drive + os.sep, "CarFleetSystem_OCR_Cache"))

    # 常见兜底路径
    if os.name == "nt":
        candidates.extend([
            r"D:\CarFleetSystem_OCR_Cache",
            r"C:\CarFleetSystem_OCR_Cache",
            r"C:\ProgramData\CarFleetSystem_OCR_Cache",
        ])
    else:
        candidates.append(os.path.join(tempfile.gettempdir(), "CarFleetSystem_OCR_Cache"))

    # 最后才使用项目内目录；如果项目路径含中文，这只是无奈兜底。
    candidates.append(os.path.join(project, "ocr_user_home"))

    for candidate in candidates:
        if _can_use_dir(candidate):
            return os.path.abspath(candidate)

    return os.path.abspath(os.path.join(project, "ocr_user_home"))


def _has_paddle_model_files(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    for root, _dirs, files in os.walk(path):
        if "inference.pdmodel" in files:
            return True
    return False


def _copy_bundled_models_to_ascii_home(ocr_home: str) -> None:
    """如果项目包里已经带了模型，启动时复制到 ASCII 缓存目录。"""
    project = _project_root()
    bundled = os.path.join(project, "ocr_user_home", ".paddleocr")
    target = os.path.join(ocr_home, ".paddleocr")

    if os.path.abspath(bundled) == os.path.abspath(target):
        return
    if _has_paddle_model_files(target):
        return
    if not _has_paddle_model_files(bundled):
        return

    try:
        shutil.copytree(bundled, target, dirs_exist_ok=True)
    except Exception:
        # 复制失败时不阻断，让 PaddleOCR 自己下载模型或抛出更明确的错误。
        pass


def _configure_ocr_environment() -> str:
    """统一设置 PaddleOCR 运行目录，返回 ASCII OCR home。"""
    global _OCR_ASCII_HOME

    if _OCR_ASCII_HOME:
        return _OCR_ASCII_HOME

    ocr_home = _choose_ascii_ocr_home()
    os.makedirs(ocr_home, exist_ok=True)

    _copy_bundled_models_to_ascii_home(ocr_home)

    # PaddleOCR 2.x 主要看 HOME/USERPROFILE；某些版本也读取 PADDLEOCR_HOME。
    os.environ["HOME"] = ocr_home
    os.environ["USERPROFILE"] = ocr_home
    os.environ["PADDLEOCR_HOME"] = os.path.join(ocr_home, ".paddleocr")
    os.environ.setdefault("PADDLE_HOME", os.path.join(ocr_home, ".paddle"))

    _OCR_ASCII_HOME = ocr_home
    return ocr_home


def _find_model_dir(ocr_home: str, kind: str) -> Optional[str]:
    """查找 det/rec/cls 的 inference 模型目录。"""
    base = os.path.join(ocr_home, ".paddleocr", "whl")
    if not os.path.isdir(base):
        return None

    kind_lower = kind.lower()
    for root, _dirs, files in os.walk(base):
        r = root.replace("\\", "/").lower()
        if kind_lower in r and "inference.pdmodel" in files:
            return root
    return None


def _ocr_tmp_dir() -> str:
    ocr_home = _configure_ocr_environment()
    path = os.path.join(ocr_home, "tmp")
    os.makedirs(path, exist_ok=True)
    return path


def _copy_file_to_ocr_tmp(image_path: str, prefix: str = "full") -> str:
    """把原图复制到 ASCII 路径，避免 Paddle 读取中文上传路径失败。"""
    try:
        ext = os.path.splitext(image_path)[1].lower() or ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
            ext = ".jpg"
        target = os.path.join(_ocr_tmp_dir(), f"{prefix}_{uuid.uuid4().hex}{ext}")
        shutil.copyfile(image_path, target)
        return target
    except Exception:
        return image_path


# =========================================================
# 基础规则
# =========================================================

PROVINCES = "京沪津渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领"

PLATE_PATTERN = re.compile(
    rf"[{PROVINCES}]"
    r"[A-Z]"
    r"[A-Z0-9]{5,6}"
)

# 兜底识别，例如 OCR 只识别出 ADL6725，没有识别出“贵”
PLATE_TAIL_PATTERN = re.compile(r"[A-Z][A-Z0-9]{5,6}")

MAX_REASONABLE_ODOMETER = 999999
MIN_FALLBACK_ODOMETER = int(OCR_MIN_AUTO_MILEAGE)

# 总里程标签的容错识别：PaddleOCR 在强反光仪表上常把“总里程”识别成
# “总里理 / 总里里 / 总理程 / 总公里”等。
# 这里不要写得过宽，避免把“累计行驶、本次行驶、续航”等误当总里程。
TOTAL_MILEAGE_LABEL_PATTERN = (
    r"总\s*[里理厘哩]\s*[程理厘哩]?"
    r"|总\s*程"
    r"|总\s*公\s*里"
    r"|ODO(?:METER)?"
    r"|ODOMETER"
    r"|TOTAL\s*MILEAGE"
    r"|TOTAL\s*KM"
)
TOTAL_MILEAGE_LABEL_RE = re.compile(TOTAL_MILEAGE_LABEL_PATTERN, re.IGNORECASE)

# V8.8：总里程标签不要只靠固定错字列表。
# 仪表反光时，“总里程”可能被 OCR 成“总里理/总理/总呈/总厘/总里/总里稆”等。
# 这里用“直接规则 + 模糊相似度 + 邻近数字”的方式判断，避免下次换一种错字又选错 3448/488。
TOTAL_LABEL_BAD_CONTEXT_RE = re.compile(
    r"本次|单次|小计|累计|续航|剩余|电量|油量|油耗|电耗|平均|速度|车速|行驶|KM/H|KWH|%",
    re.IGNORECASE,
)


def _compact_label_text(text: str) -> str:
    text = _normalize_number_chars(str(text).upper())
    # 去掉明显不是标签的数字、单位、分隔符，保留中文/英文标签骨架。
    text = text.replace("公里", "")
    text = re.sub(r"[0-9.,:：;；|/\\_\-\[\]（）(){}%\s]+", "", text)
    text = text.replace("KM", "")
    return text.strip()


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _looks_like_total_mileage_label(text: str) -> bool:
    """判断一段 OCR 文本是否像“总里程”标签。

    设计原则：
    1. 先用明确规则；
    2. 再用模糊相似度；
    3. 对“本次/累计/续航/电量”等负面上下文保持保守。
    """
    if not text:
        return False

    raw = str(text).upper()
    if TOTAL_MILEAGE_LABEL_RE.search(raw):
        return True

    compact = _compact_label_text(raw)
    if not compact:
        return False

    if "ODO" in compact or "ODOMETER" in compact or "TOTAL" in compact:
        return True

    # 如果明显是本次/累计/续航/电量一类标签，除非明确命中上面的总里程规则，否则不要当总里程。
    if TOTAL_LABEL_BAD_CONTEXT_RE.search(raw):
        return False

    # 有“总”字，并且附近有里/理/厘/哩/程/呈/公/里等形近字，认为像总里程。
    # 这样可以覆盖：总理、总厘、总里稆、总呈、总里呈、总里、总公里等。
    if "总" in compact:
        around_total = compact[max(0, compact.find("总") - 1): compact.find("总") + 6]
        if any(ch in around_total for ch in "里理厘哩程呈公稆稈"):
            return True
        if _similar(around_total, "总里程") >= 0.58:
            return True

    # 极端情况：“总”字也被识别错。只在短文本高度相似时才放行，避免误伤。
    if len(compact) <= 6 and _similar(compact, "总里程") >= 0.72:
        return True

    # 对稍长文本滑窗，找一个高度相似的短片段。
    for n in (3, 4, 5):
        if len(compact) < n:
            continue
        for i in range(0, len(compact) - n + 1):
            part = compact[i:i + n]
            if _similar(part, "总里程") >= 0.78:
                return True

    return False


def _context_has_total_mileage_label(text: str) -> bool:
    """上下文里是否包含总里程标签。

    文本里常用 |、换行、空格分隔 token。先分块判断，再整体判断，减少误判。
    """
    if not text:
        return False
    if TOTAL_MILEAGE_LABEL_RE.search(str(text)):
        return True
    parts = [p.strip() for p in re.split(r"[|\n\r]+", str(text)) if p.strip()]
    for part in parts:
        if _looks_like_total_mileage_label(part):
            return True
    return _looks_like_total_mileage_label(text)


def _split_ocr_text_parts(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"[|\n\r]+", str(text)) if p.strip()]

# 不同 ROI 对里程候选值的权重。车牌区域里的数字不应该被当作里程。
SOURCE_WEIGHT: Dict[str, int] = {
    "mileage_precise": 800,
    "mileage_left": 600,
    "left_panel": 350,
    "dashboard": 100,
    "full": 0,
    "yellow_plate": -700,
    "plate_fixed": -600,
}

_PADDLE_OCR = None
_EASYOCR_READER = None


@dataclass
class OcrResult:
    plate: Optional[str]
    mileage: Optional[int]
    raw_text: str
    confidence: float
    warnings: List[str]


@dataclass
class OcrToken:
    text: str
    confidence: float = 0.0
    source: str = "full"
    box: Optional[Any] = None


@dataclass
class OCRImage:
    path: str
    source: str


# =========================================================
# OCR 引擎：PaddleOCR 单例缓存
# =========================================================

def get_paddle_ocr():
    global _PADDLE_OCR

    if _PADDLE_OCR is not None:
        return _PADDLE_OCR

    ocr_home = _configure_ocr_environment()

    from paddleocr import PaddleOCR

    # 如果本地已有模型，显式传入 ASCII 模型路径，避免 PaddleOCR 再使用中文路径。
    model_kwargs = {}
    det_dir = _find_model_dir(ocr_home, "det")
    rec_dir = _find_model_dir(ocr_home, "rec")
    cls_dir = _find_model_dir(ocr_home, "cls")
    if det_dir:
        model_kwargs["det_model_dir"] = det_dir
    if rec_dir:
        model_kwargs["rec_model_dir"] = rec_dir
    if cls_dir:
        model_kwargs["cls_model_dir"] = cls_dir

    # V8.3：默认关闭方向分类并限制检测边长，减少 CPU 推理耗时。
    common_speed_kwargs = {
        "det_limit_side_len": OCR_DET_LIMIT_SIDE_LEN,
        "cpu_threads": OCR_CPU_THREADS,
    }

    # PaddleOCR 3.x
    try:
        _PADDLE_OCR = PaddleOCR(
            lang="ch",
            use_textline_orientation=OCR_USE_ANGLE_CLS,
            **common_speed_kwargs,
            **model_kwargs
        )
        return _PADDLE_OCR
    except Exception:
        pass

    # PaddleOCR 2.x，本项目 requirements 固定为 paddleocr==2.7.3。
    try:
        _PADDLE_OCR = PaddleOCR(
            use_angle_cls=OCR_USE_ANGLE_CLS,
            lang="ch",
            use_gpu=OCR_USE_GPU,
            show_log=False,
            use_mp=False,
            **common_speed_kwargs,
            **model_kwargs
        )
        return _PADDLE_OCR
    except Exception:
        pass

    # 最终兜底
    _PADDLE_OCR = PaddleOCR(lang="ch", **model_kwargs)
    return _PADDLE_OCR


def get_easyocr_reader():
    """仅在 PaddleOCR 不可用时兜底。"""
    global _EASYOCR_READER

    if _EASYOCR_READER is not None:
        return _EASYOCR_READER

    import easyocr  # type: ignore

    _EASYOCR_READER = easyocr.Reader(["ch_sim", "en"], gpu=False)
    return _EASYOCR_READER



# =========================================================
# 图像读取、裁剪、增强
# =========================================================

def _read_image_unicode(path: str):
    """支持中文路径读取。"""
    if cv2 is None or np is None:
        return None

    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _save_temp_image(img, prefix: str = "roi") -> str:
    # PaddleOCR 读取图片路径也要避开中文路径，所以真正用于 OCR 的临时图保存到 ASCII 目录。
    tmp_dir = _ocr_tmp_dir()
    filename = f"{prefix}_{uuid.uuid4().hex}.jpg"
    path = os.path.join(tmp_dir, filename)
    cv2.imencode(".jpg", img)[1].tofile(path)

    if OCR_DEBUG_CROPS:
        # 另存一份到项目 debug_ocr 供人工查看；OCR 不读取这个中文路径。
        try:
            debug_dir = os.path.abspath("debug_ocr")
            os.makedirs(debug_dir, exist_ok=True)
            debug_path = os.path.join(debug_dir, filename)
            cv2.imencode(".jpg", img)[1].tofile(debug_path)
        except Exception:
            pass

    return path


def _resize_limit(img, max_width: int = OCR_MAX_IMAGE_WIDTH):
    if cv2 is None or img is None:
        return img

    h, w = img.shape[:2]
    if w <= max_width:
        return img

    ratio = max_width / w
    return cv2.resize(img, (max_width, int(h * ratio)), interpolation=cv2.INTER_AREA)


def _crop_by_ratio(img, x1: float, y1: float, x2: float, y2: float):
    if img is None:
        return None

    h, w = img.shape[:2]
    left = max(0, int(w * x1))
    top = max(0, int(h * y1))
    right = min(w, int(w * x2))
    bottom = min(h, int(h * y2))

    if right <= left or bottom <= top:
        return None

    return img[top:bottom, left:right]


def _enhance_for_ocr(img, scale: int = 2, strong: bool = False):
    """轻量增强。强增强只用于小车牌区域。"""
    if cv2 is None or np is None or img is None:
        return img

    try:
        h, w = img.shape[:2]
        img = cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0 if not strong else 3.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        kernel = np.array([[0, -1, 0], [-1, 5 if not strong else 6, -1], [0, -1, 0]])
        sharp = cv2.filter2D(gray, -1, kernel)

        if strong:
            # 对黄色小车牌偶尔更有效，但不要对里程区滥用。
            sharp = cv2.bilateralFilter(sharp, 5, 35, 35)

        return sharp
    except Exception:
        return img


def _detect_yellow_plate_images(image_path: str) -> List[OCRImage]:
    """用 HSV 自动找黄色车牌区域。"""
    images: List[OCRImage] = []

    if cv2 is None or np is None:
        return images

    img = _read_image_unicode(image_path)
    if img is None:
        return images

    img = _resize_limit(img)
    h, w = img.shape[:2]

    try:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 车牌黄色范围；包含偏暗、偏亮黄。
        lower_yellow = np.array([12, 45, 70])
        upper_yellow = np.array([48, 255, 255])
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        boxes = []
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            area = bw * bh
            if area < max(500, w * h * 0.00015):
                continue
            ratio = bw / max(bh, 1)
            if ratio < 1.7 or ratio > 8.0:
                continue

            # 仪表屏里的车牌一般在中下方，避免误选上方黄色图标。
            if y < h * 0.30:
                continue

            boxes.append((x, y, bw, bh, area))

        boxes.sort(key=lambda item: item[-1], reverse=True)

        for idx, (x, y, bw, bh, area) in enumerate(boxes[:1 if OCR_FAST_MODE else 4]):
            pad_x = int(bw * 0.22)
            pad_y = int(bh * 0.45)
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(w, x + bw + pad_x)
            y2 = min(h, y + bh + pad_y)
            crop = img[y1:y2, x1:x2]
            if crop is None or crop.size == 0:
                continue

            images.append(OCRImage(_save_temp_image(crop, f"yellow_plate_{idx}"), "yellow_plate"))
            enhanced = _enhance_for_ocr(crop, scale=3, strong=True)
            if enhanced is not None:
                images.append(OCRImage(_save_temp_image(enhanced, f"yellow_plate_enh_{idx}"), "yellow_plate"))

    except Exception:
        pass

    return images


def _build_fast_ocr_images(image_path: str) -> List[OCRImage]:
    """快速模式：只生成少量关键 ROI，避免一张照片反复跑十几次 OCR。"""
    images: List[OCRImage] = []

    # 黄牌检测最多返回 1 个候选区域，通常足够识别车牌。
    images.extend(_detect_yellow_plate_images(image_path))

    if cv2 is None:
        images.append(OCRImage(_copy_file_to_ocr_tmp(image_path, "full"), "full"))
        return images

    img = _read_image_unicode(image_path)
    if img is None:
        images.append(OCRImage(_copy_file_to_ocr_tmp(image_path, "full"), "full"))
        return images

    img = _resize_limit(img)

    if OCR_FAST_MODE:
        # 默认只跑 2 个增强 ROI：一个里程区 + 一个车牌/左侧区。
        # 加上黄牌检测，总 OCR 次数通常为 3-4 次，而不是旧版 14-22 次。
        roi_specs = [
            ("mileage_precise", 0.26, 0.42, 0.52, 0.60, 2, True),
            ("plate_fixed", 0.20, 0.50, 0.50, 0.74, 2, True),
            ("mileage_left", 0.20, 0.28, 0.55, 0.68, 2, False),
        ]
    else:
        roi_specs = [
            ("mileage_left", 0.20, 0.28, 0.55, 0.68, 2, False),
            ("mileage_precise", 0.26, 0.42, 0.52, 0.60, 3, True),
            ("plate_fixed", 0.20, 0.50, 0.50, 0.74, 3, True),
            ("left_panel", 0.16, 0.24, 0.60, 0.76, 2, False),
        ]

    for name, x1, y1, x2, y2, scale, enhanced_only in roi_specs:
        if len(images) >= max(1, int(OCR_MAX_ROI_IMAGES)):
            break
        crop = _crop_by_ratio(img, x1, y1, x2, y2)
        if crop is None:
            continue
        try:
            if not enhanced_only and len(images) < max(1, int(OCR_MAX_ROI_IMAGES)):
                images.append(OCRImage(_save_temp_image(crop, name), name))
            if len(images) < max(1, int(OCR_MAX_ROI_IMAGES)):
                enhanced = _enhance_for_ocr(crop, scale=scale, strong=("plate" in name))
                if enhanced is not None:
                    images.append(OCRImage(_save_temp_image(enhanced, f"{name}_enh"), name))
        except Exception:
            continue

    return images or [OCRImage(_copy_file_to_ocr_tmp(image_path, "full"), "full")]


def _build_fallback_ocr_images(image_path: str) -> List[OCRImage]:
    """兜底模式：只有快速模式失败时才跑，减少常规耗时。"""
    images: List[OCRImage] = [OCRImage(_copy_file_to_ocr_tmp(image_path, "full"), "full")]

    if cv2 is None:
        return images

    img = _read_image_unicode(image_path)
    if img is None:
        return images

    img = _resize_limit(img)
    roi_specs = [
        ("dashboard", 0.10, 0.20, 0.96, 0.80, 1),
        ("left_panel", 0.12, 0.22, 0.66, 0.82, 2),
        ("mileage_left", 0.18, 0.30, 0.58, 0.74, 2),
    ]

    for name, x1, y1, x2, y2, scale in roi_specs:
        crop = _crop_by_ratio(img, x1, y1, x2, y2)
        if crop is None:
            continue
        try:
            images.append(OCRImage(_save_temp_image(crop, name), name))
            if scale > 1:
                enhanced = _enhance_for_ocr(crop, scale=scale, strong=False)
                if enhanced is not None:
                    images.append(OCRImage(_save_temp_image(enhanced, f"{name}_enh"), name))
        except Exception:
            continue

    return images


# =========================================================
# PaddleOCR / EasyOCR 结果解析
# =========================================================

def _is_box_like(obj: Any) -> bool:
    if not isinstance(obj, (list, tuple)) or len(obj) < 4:
        return False
    try:
        # [[x,y], [x,y], [x,y], [x,y]]
        return all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in obj[:4])
    except Exception:
        return False


def _flatten_paddle_result(obj: Any, tokens: List[OcrToken], source: str, inherited_box: Optional[Any] = None):
    if obj is None:
        return

    if isinstance(obj, str):
        text = obj.strip()
        if text:
            tokens.append(OcrToken(text=text, confidence=0.0, source=source, box=inherited_box))
        return

    if isinstance(obj, (int, float)):
        return

    if isinstance(obj, dict):
        # PaddleOCR 3.x 常见：rec_texts / rec_scores / rec_polys
        if "rec_texts" in obj:
            rec_texts = obj.get("rec_texts") or []
            rec_scores = obj.get("rec_scores") or []
            rec_boxes = obj.get("rec_polys") or obj.get("dt_polys") or obj.get("boxes") or []
            for i, t in enumerate(rec_texts):
                text = str(t).strip()
                if not text:
                    continue
                try:
                    conf = float(rec_scores[i])
                except Exception:
                    conf = 0.0
                try:
                    box = rec_boxes[i]
                except Exception:
                    box = inherited_box
                tokens.append(OcrToken(text=text, confidence=conf, source=source, box=box))

        # 其他格式兜底
        for key in ["text", "transcription", "label"]:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                conf = 0.0
                for skey in ["score", "confidence", "rec_score"]:
                    try:
                        conf = float(obj.get(skey))
                        break
                    except Exception:
                        pass
                tokens.append(OcrToken(text=value.strip(), confidence=conf, source=source, box=inherited_box))

        for value in obj.values():
            _flatten_paddle_result(value, tokens, source, inherited_box)
        return

    # PaddleOCR 3.x 对象可能有 json / to_dict
    for attr in ["json", "to_dict"]:
        try:
            value = getattr(obj, attr)
            if callable(value):
                value = value()
            _flatten_paddle_result(value, tokens, source, inherited_box)
            return
        except Exception:
            pass

    if isinstance(obj, (list, tuple)):
        # PaddleOCR 2.x: [box, (text, score)]
        if len(obj) == 2 and _is_box_like(obj[0]) and isinstance(obj[1], (list, tuple)):
            second = obj[1]
            if len(second) >= 1 and isinstance(second[0], str):
                text = second[0].strip()
                if text:
                    try:
                        conf = float(second[1]) if len(second) >= 2 else 0.0
                    except Exception:
                        conf = 0.0
                    tokens.append(OcrToken(text=text, confidence=conf, source=source, box=obj[0]))
                return

        # 如果当前列表本身是 box，向下传递。
        if _is_box_like(obj):
            inherited_box = obj

        for item in obj:
            _flatten_paddle_result(item, tokens, source, inherited_box)
        return


def _dedupe_tokens(tokens: Iterable[OcrToken]) -> List[OcrToken]:
    seen = set()
    clean: List[OcrToken] = []
    for t in tokens:
        text = str(t.text).strip()
        if not text:
            continue
        key = (text, t.source)
        if key in seen:
            continue
        seen.add(key)
        clean.append(OcrToken(text=text, confidence=float(t.confidence or 0.0), source=t.source, box=t.box))
    return clean


def _paddle_ocr_images(images: List[OCRImage]) -> Tuple[List[OcrToken], float, List[str]]:
    warnings: List[str] = []
    tokens: List[OcrToken] = []

    try:
        ocr = get_paddle_ocr()
    except Exception as exc:
        return [], 0.0, [f"PaddleOCR初始化失败：{exc}"]

    for img in images:
        try:
            result = None
            try:
                # V8.3：默认 cls=False，不跑方向分类器；仪表盘照片文字基本横向，可明显减少耗时。
                result = ocr.ocr(img.path, cls=OCR_USE_ANGLE_CLS)
            except TypeError:
                try:
                    result = ocr.ocr(img.path)
                except Exception:
                    result = None
            except Exception:
                result = None

            # PaddleOCR 3.x: 不同小版本的 predict 参数不同，两个都试。
            if result is None:
                try:
                    result = ocr.predict(img.path)
                except Exception:
                    result = None

            if result is None:
                try:
                    result = ocr.predict(input=img.path)
                except Exception:
                    result = None

            _flatten_paddle_result(result, tokens, img.source)

            # 已经拿到车牌和里程就停止后续 ROI，减少司机等待时间。
            if OCR_EARLY_STOP:
                partial = _dedupe_tokens(tokens)
                if extract_plate_from_tokens(partial) and extract_mileage_from_tokens(partial) is not None:
                    tokens = partial
                    break

        except Exception as exc:
            warnings.append(f"PaddleOCR识别图片失败：{exc}")

    tokens = _dedupe_tokens(tokens)
    confs = [float(t.confidence) for t in tokens if t.confidence]
    confidence = sum(confs) / len(confs) if confs else 0.0
    return tokens, confidence, warnings


def _easyocr_images(images: List[OCRImage]) -> Tuple[List[OcrToken], float, List[str]]:
    """PaddleOCR 不可用时兜底。"""
    warnings: List[str] = []
    tokens: List[OcrToken] = []

    try:
        reader = get_easyocr_reader()
    except Exception as exc:
        return [], 0.0, [f"备用 EasyOCR 也不可用：{exc}"]

    for img in images:
        try:
            result = reader.readtext(img.path, detail=1)
            for item in result:
                if not item or len(item) < 2:
                    continue
                text = str(item[1]).strip()
                if not text:
                    continue
                try:
                    conf = float(item[2]) if len(item) >= 3 else 0.0
                except Exception:
                    conf = 0.0
                box = item[0] if len(item) >= 1 else None
                tokens.append(OcrToken(text=text, confidence=conf, source=img.source, box=box))
        except Exception as exc:
            warnings.append(f"EasyOCR识别图片失败：{exc}")

    tokens = _dedupe_tokens(tokens)
    confs = [float(t.confidence) for t in tokens if t.confidence]
    confidence = sum(confs) / len(confs) if confs else 0.0
    return tokens, confidence, warnings


def _ocr_images(images: List[OCRImage]) -> Tuple[List[OcrToken], float, List[str]]:
    tokens, conf, warnings = _paddle_ocr_images(images)
    if tokens:
        return tokens, conf, warnings

    fallback_tokens, fallback_conf, fallback_warnings = _easyocr_images(images)
    warnings.extend(fallback_warnings)
    if fallback_tokens:
        return fallback_tokens, fallback_conf, warnings

    warnings.append("OCR未识别到有效文字，请检查照片清晰度或手动填写")
    return [], 0.0, warnings


# =========================================================
# 文本清洗与车牌识别
# =========================================================

def _normalize_plate_text(text: str) -> str:
    text = str(text).upper()
    replacements = {
        "貴": "贵",
        "責": "贵",
        "责": "贵",
        "貨": "贵",
        "货": "贵",
        "桂A": "贵A",  # 贵州车牌常被误成广西“桂”
    }
    for k, v in replacements.items():
        text = text.replace(k, v)

    text = (
        text.replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("：", "")
        .replace(":", "")
        .replace("·", "")
        .replace(".", "")
        .replace("，", "")
        .replace(",", "")
        .replace("[", "")
        .replace("]", "")
        .replace("【", "")
        .replace("】", "")
        .replace("|", "")
    )
    return text


def _normalize_plate_tail(tail: str) -> str:
    tail = str(tail).upper().strip()
    chars = list(tail)

    # 后四位更倾向数字，做轻量纠错。
    digit_like = {"O": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8"}
    start = max(0, len(chars) - 4)
    for i in range(start, len(chars)):
        chars[i] = digit_like.get(chars[i], chars[i])
    return "".join(chars)


def _valid_plate_tail(tail: str) -> bool:
    if len(tail) not in (6, 7):
        return False
    # 必须至少包含 3 个数字，避免把 TOTAL/ODOMETER 等误当车牌。
    if sum(ch.isdigit() for ch in tail) < 3:
        return False
    # 第一位为城市代码字母。
    if not tail[0].isalpha():
        return False
    return True


def extract_plate_from_text(text: str) -> Optional[str]:
    if not text:
        return None

    raw = _normalize_plate_text(text)

    match = PLATE_PATTERN.search(raw)
    if match:
        return match.group(0)

    compact = re.sub(rf"[^A-Z0-9{PROVINCES}]", "", raw)

    match = PLATE_PATTERN.search(compact)
    if match:
        return match.group(0)

    # 兜底：只识别到 ADL6725，自动补默认省份。
    candidates = []
    for m in PLATE_TAIL_PATTERN.finditer(compact):
        tail = _normalize_plate_tail(m.group(0))
        if _valid_plate_tail(tail):
            candidates.append(tail)

    if candidates:
        # 数字更多的更像车牌。
        candidates.sort(key=lambda s: (sum(c.isdigit() for c in s), len(s)), reverse=True)
        return DEFAULT_PLATE_PROVINCE + candidates[0]

    return None


def extract_plate_from_tokens(tokens: List[OcrToken]) -> Optional[str]:
    if not tokens:
        return None

    # 先用带分隔符文本，再用无分隔符拼接文本。
    joined = " | ".join(t.text for t in tokens)
    plate = extract_plate_from_text(joined)
    if plate:
        return plate

    compact_joined = "".join(t.text for t in tokens)
    return extract_plate_from_text(compact_joined)


# =========================================================
# 里程识别
# =========================================================

def _normalize_number_chars(text: str) -> str:
    table = str.maketrans({
        "Ｏ": "0", "O": "0", "o": "0",
        "Ｉ": "1", "I": "1", "l": "1",
        "，": ",", "．": ".", "：": ":",
    })
    return str(text).translate(table)


def _parse_mileage_number(value: str) -> Optional[int]:
    if value is None:
        return None
    value = _normalize_number_chars(value)
    value = re.sub(r"[^\d]", "", value)
    if not value:
        return None
    # 7位以上通常是多个数字被拼接，例如 9614692。
    if len(value) > 6:
        return None
    try:
        num = int(value)
    except Exception:
        return None
    if 0 <= num <= MAX_REASONABLE_ODOMETER:
        return num
    return None


def _numbers_in_text(text: str) -> List[Tuple[int, re.Match]]:
    t = _normalize_number_chars(text.upper())
    # 允许 53351km、53 351、53,351，不允许匹配 ADL6725 里的 6725。
    pattern = r"(?<![A-Z0-9])([0-9]{1,3}(?:[, ]?[0-9]{3})+|[0-9]{3,6})(?![0-9])"
    out: List[Tuple[int, re.Match]] = []
    for m in re.finditer(pattern, t):
        num = _parse_mileage_number(m.group(1))
        if num is None:
            continue
        out.append((num, m))
    return out


def _find_labeled_total_mileage(text: str) -> Optional[int]:
    if not text:
        return None

    t = _normalize_number_chars(text.upper())
    number = r"([0-9]{1,3}(?:[, ]?[0-9]{3})+|[0-9]{3,6})"
    labels = TOTAL_MILEAGE_LABEL_PATTERN

    # 1. 明确标签优先：总里程/ODO/TOTAL 等。
    patterns = [
        rf"(?:{labels})[^\d]{{0,80}}{number}",
        rf"{number}[^\d]{{0,24}}(?:KM|公里)[^\u4e00-\u9fa5A-Z0-9]{{0,24}}(?:{labels})",
    ]

    for pattern in patterns:
        match = re.search(pattern, t, flags=re.IGNORECASE)
        if not match:
            continue
        for group in match.groups():
            mileage = _parse_mileage_number(group)
            if mileage is not None:
                return mileage

    # 2. V8.8 模糊标签：按 OCR token 顺序找“像总里程的标签”后面的数字。
    # 例：00:00 | 3448 | 26.4 | 总呈 | 46930km | 98% | 488
    parts = _split_ocr_text_parts(t)
    seq_candidates: List[Tuple[int, int]] = []
    for i, part in enumerate(parts):
        if not _looks_like_total_mileage_label(part):
            continue

        # 标签和数字在同一块，例如“总里程46930km”。
        for num, _m in _numbers_in_text(part):
            if num >= MIN_FALLBACK_ODOMETER:
                seq_candidates.append((6000, num))

        # 数字一般紧跟在标签后 1-3 个 token 内。
        for j in range(i + 1, min(len(parts), i + 4)):
            for num, _m in _numbers_in_text(parts[j]):
                if num < MIN_FALLBACK_ODOMETER:
                    continue
                # 带 km 的候选更可靠；越近越可靠。
                score = 5800 - (j - i) * 120
                if re.search(r"KM|公里", parts[j], re.IGNORECASE):
                    score += 120
                seq_candidates.append((score, num))

        # 少数布局中数字可能在标签前一个 token。
        if i > 0:
            for num, _m in _numbers_in_text(parts[i - 1]):
                if num >= MIN_FALLBACK_ODOMETER:
                    seq_candidates.append((5200, num))

    if seq_candidates:
        seq_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return seq_candidates[0][1]

    # 3. 没有分隔符时，用数字左右 36 字符上下文做模糊判断。
    context_candidates: List[Tuple[int, int]] = []
    for num, m in _numbers_in_text(t):
        if num < MIN_FALLBACK_ODOMETER:
            continue
        before = t[max(0, m.start() - 36):m.start()]
        after = t[m.end():m.end() + 24]
        if _context_has_total_mileage_label(before) or _context_has_total_mileage_label(after):
            score = 5000
            if re.search(r"KM|公里", after, re.IGNORECASE):
                score += 80
            context_candidates.append((score, num))

    if context_candidates:
        context_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return context_candidates[0][1]

    return None

def _score_number_context(text: str, match: re.Match, source: str = "full") -> int:
    t = _normalize_number_chars(text.upper())
    start, end = match.span()
    before = t[max(0, start - 48):start]
    after = t[end:end + 48]
    context = before + " " + after
    context_upper = context.upper()

    score = SOURCE_WEIGHT.get(source, 0)

    if _context_has_total_mileage_label(context):
        score += 2600
    if re.search(r"里\s*程|里程", context):
        score += 180
    if re.search(r"KM|公里", after, re.IGNORECASE):
        score += 60

    bad_words = [
        "累计", "累计行驶", "小计", "单次", "本次", "本次行驶", "续航", "剩余",
        "电量", "油耗", "电耗", "平均", "速度", "车速", "KM/H", "KWH",
        "/100", "KW", "%", "℃", "H",
    ]
    if any(word.upper() in context_upper for word in bad_words):
        score -= 1200

    # 没有总里程标签时，小数字更可能是续航/本次行驶/电量，宁可让用户确认页手动填，也不要误填入库。
    try:
        current_num = _parse_mileage_number(match.group(1))
    except Exception:
        current_num = None
    if current_num is not None and current_num < MIN_FALLBACK_ODOMETER:
        if not _context_has_total_mileage_label(context):
            score -= 1500

    # 时间格式 00:56 / 12:23
    if ":" in before[-8:] or ":" in after[:8]:
        score -= 200

    # 车牌上下文排除。
    if re.search(r"[A-Z]", t[max(0, start - 5):start]) or re.search(r"[A-Z]", t[end:end + 5]):
        score -= 800

    return score


def extract_mileage_from_text(text: str) -> Optional[int]:
    if not text:
        return None

    labeled = _find_labeled_total_mileage(text)
    if labeled is not None:
        return labeled

    candidates: List[Tuple[int, int]] = []
    t = _normalize_number_chars(text.upper())
    for num, m in _numbers_in_text(t):
        if num < MIN_FALLBACK_ODOMETER:
            continue
        score = _score_number_context(t, m, "full")
        candidates.append((score, num))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return candidates[0][1]


def extract_mileage_from_tokens(tokens: List[OcrToken]) -> Optional[int]:
    if not tokens:
        return None

    joined = " | ".join(t.text for t in tokens)

    # 1. 全局标签优先，例如 “总里程 | 53351 km”。
    labeled = _find_labeled_total_mileage(joined)
    if labeled is not None:
        return labeled

    # 2. Token 序列中，找“总里程/ODO”标签附近的数字。V8.8 使用模糊标签，不再只靠固定错字。
    seq_candidates: List[Tuple[int, int]] = []

    for i, token in enumerate(tokens):
        text_i = str(token.text)
        if not _looks_like_total_mileage_label(text_i):
            continue

        # 同一个 token 里可能已经有数字。
        for num, m in _numbers_in_text(text_i):
            score = 5000 + SOURCE_WEIGHT.get(token.source, 0)
            seq_candidates.append((score, num))

        # 往后找 1-6 个 token，通常数字跟在“总里程”后面。
        for j in range(i + 1, min(len(tokens), i + 7)):
            t = tokens[j]
            for num, m in _numbers_in_text(t.text):
                if num < MIN_FALLBACK_ODOMETER:
                    continue
                distance_penalty = (j - i) * 80
                score = 5000 - distance_penalty + SOURCE_WEIGHT.get(t.source, 0)
                seq_candidates.append((score, num))

    if seq_candidates:
        seq_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return seq_candidates[0][1]

    # 3. 所有候选数字按上下文和 ROI 权重打分。
    candidates: List[Tuple[int, int]] = []

    # 构造每个 token 的局部上下文。
    for idx, token in enumerate(tokens):
        local_text = " | ".join(t.text for t in tokens[max(0, idx - 3): min(len(tokens), idx + 4)])
        for num, m in _numbers_in_text(token.text):
            if num < MIN_FALLBACK_ODOMETER:
                continue
            score = _score_number_context(local_text, m, token.source)
            candidates.append((score, num))

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][1]

    # 4. 最后兜底：从拼接文本里解析。
    return extract_mileage_from_text(joined)


# =========================================================
# 总入口
# =========================================================

def _raw_text_from_tokens(tokens: List[OcrToken]) -> str:
    return " | ".join(t.text for t in tokens if t.text)


def _merge_tokens(a: List[OcrToken], b: List[OcrToken]) -> List[OcrToken]:
    return _dedupe_tokens(list(a) + list(b))


def _write_last_ocr_debug(image_path: str, tokens: List[OcrToken], warnings: List[str], stage: str):
    """
    V7.1 调试输出：
    每次识别后写 debug_ocr/last_ocr.txt。
    如果页面提示未识别到车牌或里程，先看这个文件。
    """
    if not OCR_DEBUG_ALWAYS and not OCR_DEBUG_CROPS:
        return

    try:
        debug_dir = os.path.abspath("debug_ocr")
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, "last_ocr.txt")

        lines = []
        lines.append(f"stage: {stage}")
        lines.append(f"image_path: {image_path}")
        lines.append(f"ocr_fast_mode: {OCR_FAST_MODE}")
        lines.append(f"ocr_fallback_enabled: {OCR_FALLBACK_ENABLED}")
        lines.append(f"ocr_early_stop: {OCR_EARLY_STOP}")
        lines.append(f"ocr_use_angle_cls: {OCR_USE_ANGLE_CLS}")
        lines.append(f"ocr_max_roi_images: {OCR_MAX_ROI_IMAGES}")
        lines.append(f"ocr_min_auto_mileage: {OCR_MIN_AUTO_MILEAGE}")
        try:
            ocr_home = _configure_ocr_environment()
            lines.append(f"ocr_home: {ocr_home}")
            lines.append(f"ocr_home_is_ascii: {_is_ascii_path(ocr_home)}")
            lines.append(f"model_files_found: {_has_paddle_model_files(os.path.join(ocr_home, '.paddleocr'))}")
        except Exception as exc:
            lines.append(f"ocr_home_check_failed: {exc}")
        lines.append("")
        lines.append("warnings:")
        if warnings:
            for w in warnings:
                lines.append(f"- {w}")
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("tokens:")
        if tokens:
            for i, t in enumerate(tokens, 1):
                lines.append(
                    f"{i}. text={t.text!r} | conf={float(t.confidence or 0):.4f} | source={t.source}"
                )
        else:
            lines.append("- 无OCR文本")
        lines.append("")
        lines.append("raw_text:")
        lines.append(_raw_text_from_tokens(tokens))

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def recognize_vehicle_image(image_path: str) -> OcrResult:
    warnings: List[str] = []

    fast_images = _build_fast_ocr_images(image_path)
    fast_tokens, fast_confidence, fast_warnings = _ocr_images(fast_images)
    warnings.extend(fast_warnings)

    plate = extract_plate_from_tokens(fast_tokens)
    mileage = extract_mileage_from_tokens(fast_tokens)

    if plate and mileage is not None:
        _write_last_ocr_debug(image_path, fast_tokens, warnings, "fast_success")
        return OcrResult(
            plate=plate,
            mileage=mileage,
            raw_text=_raw_text_from_tokens(fast_tokens),
            confidence=fast_confidence,
            warnings=warnings,
        )

    if OCR_FALLBACK_ENABLED:
        fallback_images = _build_fallback_ocr_images(image_path)
        fallback_tokens, fallback_confidence, fallback_warnings = _ocr_images(fallback_images)
        warnings.extend(fallback_warnings)
        all_tokens = _merge_tokens(fast_tokens, fallback_tokens)
        confidence = max(fast_confidence or 0.0, fallback_confidence or 0.0)
    else:
        warnings.append("快速OCR未完全识别，已跳过耗时兜底模式；可手动校正，或设置 OCR_FALLBACK_ENABLED=1 提高识别率")
        all_tokens = fast_tokens
        confidence = fast_confidence or 0.0

    plate = extract_plate_from_tokens(all_tokens)
    mileage = extract_mileage_from_tokens(all_tokens)

    if confidence and confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(f"OCR平均置信度较低：{confidence:.2f}")
    if not plate:
        warnings.append("未能自动识别车牌号，请手动填写")
    if mileage is None:
        warnings.append("未能自动识别总里程，请手动填写")

    _write_last_ocr_debug(image_path, all_tokens, warnings, "final")

    return OcrResult(
        plate=plate,
        mileage=mileage,
        raw_text=_raw_text_from_tokens(all_tokens),
        confidence=confidence,
        warnings=warnings,
    )


# =========================================================
# 兼容旧代码
# =========================================================

def extract_mileage(image_path: str) -> Optional[int]:
    return recognize_vehicle_image(image_path).mileage


def extract_plate(image_path: str) -> Optional[str]:
    return recognize_vehicle_image(image_path).plate


# =========================================================
# 本地文本规则测试
# =========================================================

if __name__ == "__main__":
    test_text = """
    本次行驶
    00:56
    81 km
    20.1 kWh/100km
    累计行驶
    4612
    19.7 kWh/100km
    总里程: 53351 km
    贵ADL6725
    29%
    146 km
    12:23
    """
    print("车牌测试：", extract_plate_from_text(test_text))
    print("里程测试：", extract_mileage_from_text(test_text))
