import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from werkzeug.utils import secure_filename

from config import UPLOAD_DIR

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}
WINDOWS_INVALID_CHARS = r'<>:"/\\|?*'


def _get_ext(filename: str) -> str:
    """
    Robustly extract extension from the *original* uploaded filename.
    Do not extract it from secure_filename(filename), because Chinese or
    unusual filenames may be cleaned into a string without a dot.
    """
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return suffix


def allowed_file(filename: str) -> bool:
    return _get_ext(filename) in ALLOWED_EXTENSIONS


def save_upload(file_storage, prefix: str) -> str:
    """
    Save an uploaded image and return its server-side path.

    The final business name is generated after OCR because plate number is
    unknown before recognition. See rename_trip_photo().
    """
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("没有上传图片")

    original_filename = file_storage.filename
    ext = _get_ext(original_filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("图片格式不支持，请上传 png/jpg/jpeg/webp/bmp")

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    safe_original = secure_filename(original_filename) or "upload"
    safe_stem = Path(safe_original).stem or "upload"

    # 先保存到临时安全文件名，OCR 完成后再按“用户名+车牌号+时间.jpg”重命名。
    filename = f"{prefix}_{uuid.uuid4().hex}_{safe_stem}.{ext}"
    full_path = os.path.join(UPLOAD_DIR, filename)
    file_storage.save(full_path)
    return full_path




def save_upload_optional(file_storage, prefix: str) -> Optional[str]:
    """
    Optional image upload.

    Manual mileage mode does not require a photo/OCR. Return None when the
    user did not upload an image; otherwise reuse save_upload validation.
    """
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    return save_upload(file_storage, prefix)

def _safe_filename_part(value: Optional[str], fallback: str = "unknown") -> str:
    value = str(value or "").strip() or fallback
    for ch in WINDOWS_INVALID_CHARS:
        value = value.replace(ch, "_")
    value = re.sub(r"\s+", "_", value)
    value = value.strip("._ ")
    return value or fallback


def _format_photo_time(value=None) -> str:
    if value is None:
        dt = datetime.now()
    elif isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d_%H%M%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except Exception:
                dt = None
        if dt is None:
            # 兜底：只保留数字，避免冒号等非法字符。
            digits = re.sub(r"\D", "", text)
            return digits[:14] if digits else datetime.now().strftime("%Y%m%d_%H%M%S")
    return dt.strftime("%Y%m%d_%H%M%S")


def build_trip_photo_filename(username: str, plate: str, time_value=None) -> str:
    """生成：用户名_车牌号_时间.jpg。"""
    user_part = _safe_filename_part(username, "user")
    plate_part = _safe_filename_part(plate, "plate")
    time_part = _format_photo_time(time_value)
    return f"{user_part}_{plate_part}_{time_part}.jpg"


def _unique_path(directory: str, filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".jpg"
    candidate = os.path.join(directory, filename)
    index = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}_{index}{suffix}")
        index += 1
    return candidate


def copy_image_as_jpg(src_path: str, dest_path: str) -> None:
    """复制/转换为 jpg。优先用 OpenCV 转码，失败时直接复制原文件。"""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        data = np.fromfile(src_path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("cv2 imdecode failed")
        ok, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ok:
            raise ValueError("cv2 imencode failed")
        encoded.tofile(dest_path)
    except Exception:
        shutil.copyfile(src_path, dest_path)


def rename_trip_photo(image_path: str, username: str, plate: str, time_value=None) -> str:
    """
    OCR 成功后，把上传图片改名为：用户名_车牌号_时间.jpg。
    返回新路径；如果转换/重命名失败，返回原路径，避免影响业务提交。
    """
    if not image_path or not os.path.exists(image_path):
        return image_path

    try:
        directory = os.path.dirname(image_path) or UPLOAD_DIR
        os.makedirs(directory, exist_ok=True)
        filename = build_trip_photo_filename(username, plate, time_value)
        target = _unique_path(directory, filename)
        copy_image_as_jpg(image_path, target)
        if os.path.abspath(target) != os.path.abspath(image_path):
            try:
                os.remove(image_path)
            except Exception:
                pass
        return target
    except Exception:
        return image_path
