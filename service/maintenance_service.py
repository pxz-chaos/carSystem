import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from config import DB_PATH, EXPORT_DIR, UPLOAD_DIR
from dao.record_dao import get_conn
from utils.file_utils import build_trip_photo_filename, copy_image_as_jpg


COLUMN_MAP = {
    "id": "编号",
    "username": "用户",
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
    "warning": "异常提示",
    "start_photo": "出发照片",
    "end_photo": "回场照片",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _subtract_months(dt: datetime, months: int) -> datetime:
    """不额外依赖 dateutil 的月份回退。"""
    months = max(0, int(months))
    year = dt.year
    month = dt.month - months
    while month <= 0:
        month += 12
        year -= 1
    # 保守处理月末：如果目标月没有当天，取该月最后一天。
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, days_in_month[month - 1])
    return dt.replace(year=year, month=month, day=day)


def cutoff_for_months(months: int) -> str:
    return _subtract_months(datetime.now(), months).strftime("%Y-%m-%d %H:%M:%S")


def _dir_size_and_count(path: str) -> Tuple[int, int]:
    total = 0
    count = 0
    if not path or not os.path.isdir(path):
        return 0, 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += os.path.getsize(fp)
                count += 1
            except Exception:
                pass
    return total, count


def format_bytes(size: int) -> str:
    size = int(size or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def get_storage_stats() -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = _safe_int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM trip_records")
    trip_count = _safe_int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM sms_codes")
    sms_count = _safe_int(cur.fetchone()[0])
    cur.execute("SELECT MIN(COALESCE(end_time, start_time, date)), MAX(COALESCE(end_time, start_time, date)) FROM trip_records")
    span = cur.fetchone()
    conn.close()

    db_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    upload_bytes, upload_files = _dir_size_and_count(UPLOAD_DIR)
    export_bytes, export_files = _dir_size_and_count(EXPORT_DIR)

    # 统计孤儿图片：uploads 中存在，但数据库行程记录已经不引用的图片。
    refs = _remaining_photo_refs()
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    orphan_bytes = 0
    orphan_files = 0
    referenced_photo_files = 0
    for fp in list(_iter_files(UPLOAD_DIR) or []):
        if Path(fp).suffix.lower() not in image_exts:
            continue
        abs_fp = os.path.abspath(fp)
        if abs_fp in refs:
            referenced_photo_files += 1
        else:
            orphan_files += 1
            try:
                orphan_bytes += os.path.getsize(fp)
            except Exception:
                pass

    return {
        "user_count": user_count,
        "trip_count": trip_count,
        "sms_count": sms_count,
        "oldest_record_time": span[0] if span else None,
        "newest_record_time": span[1] if span else None,
        "db_bytes": db_bytes,
        "db_size": format_bytes(db_bytes),
        "upload_bytes": upload_bytes,
        "upload_size": format_bytes(upload_bytes),
        "upload_files": upload_files,
        "referenced_photo_files": referenced_photo_files,
        "orphan_photo_files": orphan_files,
        "orphan_photo_bytes": orphan_bytes,
        "orphan_photo_size": format_bytes(orphan_bytes),
        "export_bytes": export_bytes,
        "export_size": format_bytes(export_bytes),
        "export_files": export_files,
        "total_bytes": db_bytes + upload_bytes + export_bytes,
        "total_size": format_bytes(db_bytes + upload_bytes + export_bytes),
    }


def get_records_older_than(cutoff_time: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM trip_records
        WHERE COALESCE(end_time, start_time, date) < ?
        ORDER BY COALESCE(end_time, start_time, date) ASC, id ASC
        """,
        (cutoff_time,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def _photo_display_name(path: Optional[str]) -> str:
    return os.path.basename(str(path)) if path else ""


def _unique_arcname(used: Dict[str, int], filename: str) -> str:
    if filename not in used:
        used[filename] = 0
        return filename
    used[filename] += 1
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".jpg"
    return f"{stem}_{used[filename]}{suffix}"


def archive_records(rows: List[Dict[str, Any]], label: str = "cleanup") -> Optional[str]:
    if not rows:
        return None
    os.makedirs(EXPORT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(EXPORT_DIR, f"archive_{label}_{ts}.zip")
    excel_path = os.path.join(EXPORT_DIR, f".__archive_records_{ts}.xlsx")
    used_names: Dict[str, int] = {}
    temp_files: List[str] = [excel_path]

    try:
        df = pd.DataFrame(rows)
        keep_cols = [c for c in COLUMN_MAP.keys() if c in df.columns]
        if keep_cols:
            df = df[keep_cols].rename(columns=COLUMN_MAP)
        for col in ["出发照片", "回场照片"]:
            if col in df.columns:
                df[col] = df[col].map(_photo_display_name)
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="归档行程记录")
            worksheet = writer.sheets["归档行程记录"]
            for column_cells in worksheet.columns:
                max_length = max(len(str(cell.value or "")) for cell in column_cells)
                worksheet.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 35)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(excel_path, arcname="归档行程记录.xlsx")
            for row in rows:
                user = row.get("username") or "user"
                plate = row.get("plate") or "plate"
                for photo_key, time_key, folder in (
                    ("start_photo", "start_time", "出发照片"),
                    ("end_photo", "end_time", "回场照片"),
                ):
                    src = row.get(photo_key)
                    if not src or not os.path.exists(str(src)):
                        continue
                    desired = build_trip_photo_filename(user, plate, row.get(time_key))
                    arcname = folder + "/" + _unique_arcname(used_names, desired)
                    tmp_img = os.path.join(EXPORT_DIR, f".__archive_{Path(arcname).name}")
                    temp_files.append(tmp_img)
                    try:
                        copy_image_as_jpg(str(src), tmp_img)
                        zf.write(tmp_img, arcname=arcname)
                    except Exception:
                        # 单张图片归档失败不影响数据库归档。
                        pass
        return zip_path
    finally:
        for fp in temp_files:
            try:
                if os.path.exists(fp):
                    os.remove(fp)
            except Exception:
                pass


def _remaining_photo_refs() -> set:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT start_photo, end_photo FROM trip_records")
    refs = set()
    for row in cur.fetchall():
        for value in row:
            if value:
                refs.add(os.path.abspath(str(value)))
    conn.close()
    return refs


def delete_records_by_ids(ids: Iterable[int]) -> int:
    ids = [int(x) for x in ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM trip_records WHERE id IN ({placeholders})", ids)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return int(deleted or 0)


def cleanup_expired_sms_codes() -> int:
    now = int(datetime.now().timestamp())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sms_codes WHERE used_at IS NOT NULL OR expires_at < ?", (now,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return int(deleted or 0)


def vacuum_database() -> None:
    conn = get_conn()
    conn.execute("VACUUM")
    conn.close()




def get_referenced_photo_paths() -> set:
    """返回数据库中仍被行程记录引用的照片绝对路径。"""
    return _remaining_photo_refs()


def _iter_files(path: str):
    if not path or not os.path.isdir(path):
        return
    for root, _dirs, files in os.walk(path):
        for name in files:
            yield os.path.join(root, name)


def cleanup_orphan_upload_photos() -> Dict[str, Any]:
    """删除 uploads 目录里没有被任何行程记录引用的孤儿图片。"""
    refs = _remaining_photo_refs()
    deleted = 0
    deleted_bytes = 0
    matched = 0

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for path in list(_iter_files(UPLOAD_DIR) or []):
        ext = Path(path).suffix.lower()
        if ext not in image_exts:
            continue
        abs_path = os.path.abspath(path)
        if abs_path in refs:
            continue
        matched += 1
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        try:
            os.remove(path)
            deleted += 1
            deleted_bytes += size
        except Exception:
            pass

    return {
        "matched_orphan_photos": matched,
        "deleted_orphan_photos": deleted,
        "deleted_orphan_photo_bytes": deleted_bytes,
        "deleted_orphan_photo_size": format_bytes(deleted_bytes),
    }


def cleanup_export_files() -> Dict[str, Any]:
    """删除导出目录中的临时 Excel/ZIP 等导出文件，不影响数据库和上传照片。"""
    deleted = 0
    deleted_bytes = 0
    matched = 0
    for path in list(_iter_files(EXPORT_DIR) or []):
        if os.path.basename(path).startswith("."):
            # 隐藏临时文件也允许清理，但先计入。
            pass
        matched += 1
        try:
            size = os.path.getsize(path)
        except Exception:
            size = 0
        try:
            os.remove(path)
            deleted += 1
            deleted_bytes += size
        except Exception:
            pass
    return {
        "matched_export_files": matched,
        "deleted_export_files": deleted,
        "deleted_export_bytes": deleted_bytes,
        "deleted_export_size": format_bytes(deleted_bytes),
    }

def cleanup_old_data(
    retention_months: int,
    backup_before_delete: bool = True,
    delete_photos: bool = True,
    vacuum: bool = True,
) -> Dict[str, Any]:
    """清理指定月份以前的行程记录。

    retention_months=6 表示保留最近 6 个月；
    retention_months=0 表示管理员手动清理全部当前行程记录。
    自动清理仍然要求 DATA_RETENTION_MONTHS > 0，避免误删全部数据。
    """
    retention_months = int(retention_months or 0)
    if retention_months < 0:
        raise ValueError("保留月份不能小于 0")

    cutoff = cutoff_for_months(retention_months)
    rows = get_records_older_than(cutoff)
    label = "all_before_now" if retention_months == 0 else f"older_than_{retention_months}m"
    archive_path = archive_records(rows, label=label) if backup_before_delete and rows else None

    photo_paths: List[str] = []
    for row in rows:
        for key in ("start_photo", "end_photo"):
            path = row.get(key)
            if path:
                photo_paths.append(str(path))

    deleted_records = delete_records_by_ids([row["id"] for row in rows]) if rows else 0

    deleted_photos = 0
    if delete_photos and photo_paths:
        remaining_refs = _remaining_photo_refs()
        for path in photo_paths:
            abs_path = os.path.abspath(path)
            if abs_path in remaining_refs:
                continue
            try:
                if os.path.exists(path):
                    os.remove(path)
                    deleted_photos += 1
            except Exception:
                pass

    deleted_sms = cleanup_expired_sms_codes()
    if vacuum and (deleted_records or deleted_sms):
        try:
            vacuum_database()
        except Exception:
            pass

    return {
        "cutoff_time": cutoff,
        "matched_records": len(rows),
        "deleted_records": deleted_records,
        "deleted_photos": deleted_photos,
        "deleted_sms_codes": deleted_sms,
        "archive_path": archive_path,
    }
