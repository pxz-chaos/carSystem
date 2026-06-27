import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import BASE_DIR, EXPORT_DIR, UPLOAD_DIR
from dao.record_dao import get_all_records, get_user_records
from utils.file_utils import build_trip_photo_filename, copy_image_as_jpg

# Excel 不导出经纬度，只保留可读地址。
COLUMN_MAP = {
    "id": "编号",
    "username": "用户",
    "gender": "性别",
    "unit": "单位",
    "department": "部门",
    "team": "班组",
    "plate": "车牌号",
    "date": "日期",
    "start_mileage": "出发里程",
    "end_mileage": "回场里程",
    "distance": "本次行驶里程KM",
    "start_time": "出发时间",
    "end_time": "回场时间",
    "start_address": "出发地点",
    "end_address": "回场地点",
    "status": "状态",
    "start_photo": "出发照片",
    "end_photo": "回场照片",
    "warning": "异常提示",
}

# openpyxl / Excel 不允许写入部分控制字符，否则会触发 Internal Server Error。
_ILLEGAL_EXCEL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_export_dir() -> None:
    os.makedirs(EXPORT_DIR, exist_ok=True)


def _excel_safe_value(value: Any) -> Any:
    """清理 Excel 不支持的字符，避免导出时报错。"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    text = _ILLEGAL_EXCEL_RE.sub("", text)
    # Excel 单元格最大约 32767 字符，超长文本截断，防止写入失败。
    if len(text) > 32760:
        text = text[:32760] + "..."
    return text


def _photo_display_name(path: Optional[str]) -> str:
    if not path:
        return ""
    return os.path.basename(str(path))


def _rows_for_export(username: Optional[str]) -> List[Dict[str, Any]]:
    rows = get_user_records(username) if username else get_all_records()
    return [dict(row) for row in rows]


def export_excel(username: Optional[str] = None) -> str:
    """
    导出 Excel。
    不依赖 pandas，直接使用 openpyxl，减少上线环境兼容问题。
    """
    _ensure_export_dir()

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except Exception as exc:
        raise RuntimeError("缺少 openpyxl，无法导出 Excel。请重新运行 setup_env.bat 或执行：venv\\Scripts\\python.exe -m pip install openpyxl==3.1.5") from exc

    rows = _rows_for_export(username)
    headers = list(COLUMN_MAP.values())
    keys = list(COLUMN_MAP.keys())

    wb = Workbook()
    ws = wb.active
    ws.title = "行程记录"

    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in rows:
        values = []
        for key in keys:
            value = row.get(key, "")
            if key in {"start_photo", "end_photo"}:
                value = _photo_display_name(value)
            values.append(_excel_safe_value(value))
        ws.append(values)

    # 自动列宽。
    for column_cells in ws.columns:
        max_length = 0
        for cell in column_cells:
            max_length = max(max_length, len(str(cell.value or "")))
        ws.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 35)

    filename = f"trip_records_{_now_stamp()}.xlsx"
    path = os.path.join(EXPORT_DIR, filename)
    wb.save(path)
    return path


def _unique_arcname(used: Dict[str, int], filename: str) -> str:
    if filename not in used:
        used[filename] = 0
        return filename
    used[filename] += 1
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".jpg"
    return f"{stem}_{used[filename]}{suffix}"


def _resolve_photo_path(src: Any) -> Optional[str]:
    """兼容数据库里保存绝对路径、项目相对路径、uploads 文件名三种情况。"""
    if not src:
        return None
    text = str(src).strip()
    if not text:
        return None

    candidates = []
    if os.path.isabs(text):
        candidates.append(text)
    else:
        candidates.append(os.path.join(BASE_DIR, text))
        candidates.append(os.path.join(UPLOAD_DIR, text))
        candidates.append(os.path.join(UPLOAD_DIR, os.path.basename(text)))

    for candidate in candidates:
        if os.path.exists(candidate) and os.path.isfile(candidate):
            return candidate
    return None


def export_images_zip(username: Optional[str] = None) -> str:
    """导出图片压缩包，图片名为：用户名_车牌号_时间.jpg。"""
    _ensure_export_dir()
    rows = _rows_for_export(username)
    filename = f"trip_images_{_now_stamp()}.zip"
    zip_path = os.path.join(EXPORT_DIR, filename)
    used_names: Dict[str, int] = {}

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            user = row.get("username") or username or "user"
            plate = row.get("plate") or "plate"
            for photo_key, time_key in (("start_photo", "start_time"), ("end_photo", "end_time")):
                src_path = _resolve_photo_path(row.get(photo_key))
                if not src_path:
                    continue

                desired_name = build_trip_photo_filename(user, plate, row.get(time_key))
                arcname = _unique_arcname(used_names, desired_name)
                temp_jpg = os.path.join(EXPORT_DIR, f".__tmp_{arcname}")
                try:
                    copy_image_as_jpg(src_path, temp_jpg)
                    zf.write(temp_jpg, arcname=arcname)
                finally:
                    try:
                        if os.path.exists(temp_jpg):
                            os.remove(temp_jpg)
                    except Exception:
                        pass

    return zip_path
