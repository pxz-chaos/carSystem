"""Upload/image utilities optimized for small cloud servers.

Key changes:
- accept the original formats, but store every upload as compressed JPEG;
- strip EXIF metadata to protect privacy and reduce size;
- cap image dimensions before OCR/storage;
- shard uploads by year/month/day to avoid a single huge directory;
- avoid OpenCV for simple image conversion, reducing memory pressure.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from werkzeug.utils import secure_filename

from config import UPLOAD_DIR

try:
    from PIL import Image, ImageOps, ImageFile  # type: ignore

    ImageFile.LOAD_TRUNCATED_IMAGES = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageOps = None  # type: ignore

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}
WINDOWS_INVALID_CHARS = r'<>:"/\\|?*'


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return int(default)


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _get_ext(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    return "jpg" if suffix == "jpeg" else suffix


def allowed_file(filename: str) -> bool:
    return _get_ext(filename) in ALLOWED_EXTENSIONS


def _safe_filename_part(value: Optional[str], fallback: str = "unknown") -> str:
    value = str(value or "").strip() or fallback
    for ch in WINDOWS_INVALID_CHARS:
        value = value.replace(ch, "_")
    value = re.sub(r"\s+", "_", value)
    value = value.strip("._ ")
    return value or fallback


def _upload_subdir() -> str:
    now = datetime.now()
    directory = os.path.join(UPLOAD_DIR, f"{now:%Y}", f"{now:%m}", f"{now:%d}")
    os.makedirs(directory, exist_ok=True)
    return directory


def _jpeg_quality() -> int:
    return max(45, min(95, _env_int("IMAGE_JPEG_QUALITY", "75")))


def _max_dimension() -> int:
    return max(640, min(4096, _env_int("IMAGE_MAX_DIMENSION", os.environ.get("IMAGE_MAX_WIDTH", "1280"))))


def _compress_to_jpg(src_path: str, dest_path: str, quality: Optional[int] = None) -> None:
    if Image is None or ImageOps is None:
        # Last resort. Keep the business path working, even if Pillow is missing.
        shutil.copyfile(src_path, dest_path)
        return
    with Image.open(src_path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        max_dim = _max_dimension()
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        img.save(
            dest_path,
            format="JPEG",
            quality=int(quality or _jpeg_quality()),
            optimize=True,
            progressive=True,
        )


def save_upload(file_storage, prefix: str) -> str:
    """Save an uploaded image as an optimized JPEG and return server-side path."""
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("没有上传图片")

    original_filename = file_storage.filename
    ext = _get_ext(original_filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("图片格式不支持，请上传 png/jpg/jpeg/webp/bmp")

    max_mb = _env_int("MAX_CONTENT_LENGTH_MB", "8")
    content_length = getattr(file_storage, "content_length", None) or 0
    if content_length and content_length > max_mb * 1024 * 1024:
        raise ValueError(f"图片不能超过 {max_mb}MB，请压缩后再上传")

    safe_original = secure_filename(original_filename) or "upload"
    safe_stem = Path(safe_original).stem or "upload"
    directory = _upload_subdir()
    tmp_path = os.path.join(directory, f".__raw_{prefix}_{uuid.uuid4().hex}_{safe_stem}.{ext}")
    final_path = os.path.join(directory, f"{prefix}_{uuid.uuid4().hex}_{safe_stem}.jpg")

    try:
        file_storage.save(tmp_path)
        if os.path.getsize(tmp_path) > max_mb * 1024 * 1024:
            raise ValueError(f"图片不能超过 {max_mb}MB，请压缩后再上传")
        _compress_to_jpg(tmp_path, final_path)
        return final_path
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def save_upload_optional(file_storage, prefix: str) -> Optional[str]:
    if not file_storage or not getattr(file_storage, "filename", None):
        return None
    return save_upload(file_storage, prefix)


def _format_photo_time(value=None) -> str:
    if value is None:
        dt = datetime.now()
    elif isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d_%H%M%S"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except Exception:
                pass
        if dt is None:
            digits = re.sub(r"\D", "", text)
            return digits[:14] if digits else datetime.now().strftime("%Y%m%d_%H%M%S")
    return dt.strftime("%Y%m%d_%H%M%S")


def build_trip_photo_filename(username: str, plate: str, time_value=None) -> str:
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
    """Copy/convert an image as JPEG, using Pillow to avoid loading OpenCV."""
    try:
        _compress_to_jpg(src_path, dest_path, quality=_env_int("IMAGE_EXPORT_JPEG_QUALITY", "85"))
    except Exception:
        shutil.copyfile(src_path, dest_path)


def rename_trip_photo(image_path: str, username: str, plate: str, time_value=None) -> str:
    """Rename/convert uploaded photo as 用户名_车牌号_时间.jpg."""
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
