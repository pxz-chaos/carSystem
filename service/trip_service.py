from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Optional

from config import MAX_SINGLE_TRIP_KM, ODO_ROLLOVER
from dao.record_dao import create_start_trip, finish_trip as dao_finish_trip, get_trip_by_id
from utils.location_utils import clean_float, format_location
from utils.ocr_utils import recognize_vehicle_image
from utils.file_utils import rename_trip_photo


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _manual_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        num = int(text)
    except Exception:
        raise ValueError("手动里程必须是整数")
    if num < 0:
        raise ValueError("里程不能小于 0")
    if num > 999999:
        raise ValueError("里程不能超过 999999")
    return num


def _join_warnings(*items) -> str:
    warnings = []
    for item in items:
        if not item:
            continue
        if isinstance(item, list):
            warnings.extend(str(x) for x in item if x)
        else:
            warnings.append(str(item))
    # 去重但保留顺序，避免页面提示太长
    clean = []
    seen = set()
    for w in warnings:
        w = str(w).strip()
        if not w or w in seen:
            continue
        seen.add(w)
        clean.append(w)
    return "；".join(clean)


def _ocr_debug_brief(ocr) -> str:
    """
    把 OCR 失败原因显示到页面上，避免只看到“未识别到”却不知道是依赖没装、OCR为空，还是裁剪没对准。
    """
    parts = []

    raw = getattr(ocr, "raw_text", "") or ""
    if raw:
        parts.append("OCR原文：" + raw[:300])
    else:
        parts.append("OCR原文为空")

    warnings = getattr(ocr, "warnings", []) or []
    if warnings:
        parts.append("OCR警告：" + "；".join(str(x) for x in warnings[:5]))

    conf = getattr(ocr, "confidence", None)
    if conf is not None:
        try:
            parts.append(f"OCR置信度：{float(conf):.3f}")
        except Exception:
            pass

    parts.append("更多详情见项目根目录 debug_ocr/last_ocr.txt")
    return "；".join(parts)


def _empty_ocr_result(reason: str = "未执行自动识别"):
    return SimpleNamespace(
        plate=None,
        mileage=None,
        raw_text="",
        confidence=0.0,
        warnings=[reason] if reason else [],
    )


def _maybe_recognize_vehicle_image(image_path: Optional[str], reason_when_skipped: str):
    """Only run OCR when an image exists and automatic recognition is needed."""
    if not image_path:
        return _empty_ocr_result(reason_when_skipped)
    return recognize_vehicle_image(image_path)


def _normalize_plate(value) -> str:
    value = str(value or "").strip().upper()
    return value.replace(" ", "").replace("-", "").replace("_", "")


def _ocr_to_dict(ocr) -> Dict[str, Any]:
    return {
        "plate": getattr(ocr, "plate", None),
        "mileage": getattr(ocr, "mileage", None),
        "raw_text": getattr(ocr, "raw_text", "") or "",
        "confidence": float(getattr(ocr, "confidence", 0.0) or 0.0),
        "warnings": list(getattr(ocr, "warnings", []) or []),
        "debug": _ocr_debug_brief(ocr),
    }


def preview_vehicle_ocr(image_path: str, plate_override=None, mileage_override=None) -> Dict[str, Any]:
    """
    自动识别只做“预填建议”，不直接入库。
    页面必须让用户确认或修改后再调用 start_trip / finish_running_trip 保存。
    """
    if not image_path:
        raise ValueError("请先上传照片，或直接手动填写信息")

    manual_plate = _normalize_plate(plate_override)
    manual_mileage = _manual_int(mileage_override)
    ocr = recognize_vehicle_image(image_path)

    result = _ocr_to_dict(ocr)
    if manual_plate:
        result["plate"] = manual_plate
        result["warnings"].append("车牌号沿用用户手动输入值，OCR仅作为辅助")
    if manual_mileage is not None:
        result["mileage"] = manual_mileage
        result["warnings"].append("里程沿用用户手动输入值，OCR仅作为辅助")

    result["confirmed_required"] = True
    result["warnings"].append("自动识别结果不会直接入库，必须人工确认或修改后提交")
    return result


def _ocr_context_to_warnings(ocr_context: Optional[Dict[str, Any]], confirmed_label: str) -> list:
    warnings = []
    if not ocr_context:
        return warnings
    confidence = ocr_context.get("confidence")
    try:
        warnings.append(f"{confirmed_label}；OCR置信度：{float(confidence or 0):.3f}")
    except Exception:
        warnings.append(confirmed_label)
    for w in ocr_context.get("warnings") or []:
        ws = str(w).strip()
        if ws:
            warnings.append(ws)
    return warnings


def calculate_distance(start_mileage: int, end_mileage: int) -> Dict[str, Any]:
    warnings = []
    if start_mileage is None or end_mileage is None:
        raise ValueError("起始里程或回场里程为空，无法计算")

    start = int(start_mileage)
    end = int(end_mileage)

    if end >= start:
        distance = end - start
    else:
        # 只有“接近最大里程且回场读数很小”才按里程表回零处理。
        # 例如 999900 -> 120 可视为回零；53351 -> 46930 不应强行归零。
        rollover_distance = (ODO_ROLLOVER - start) + end
        near_rollover = start >= int(ODO_ROLLOVER * 0.90) and end <= MAX_SINGLE_TRIP_KM
        if near_rollover and rollover_distance <= MAX_SINGLE_TRIP_KM:
            distance = rollover_distance
            warnings.append("检测到里程表可能回零，已按回零逻辑计算")
        else:
            distance = None
            warnings.append("回场里程小于出发里程，疑似OCR识别错误或录入错误，未自动计算本次行驶里程，请人工复核")

    if distance is not None and distance > MAX_SINGLE_TRIP_KM:
        warnings.append(f"单次行驶里程超过阈值 {MAX_SINGLE_TRIP_KM} KM，请复核")

    return {"distance": distance, "warnings": warnings}


def start_trip(username: str, image_path: Optional[str], lat, lng, plate_override=None, mileage_override=None, ocr_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    出车登记：手动输入优先，自动识别必须人工确认。

    - 同时填写车牌号和出发里程：直接保存，不运行 OCR；
    - 自动识别只用于预填；确认页提交后，以页面上的确认值入库；
    - 缺少必要字段且无照片：提示手动填写。
    """
    manual_plate = _normalize_plate(plate_override)
    manual_mileage = _manual_int(mileage_override)

    need_ocr = bool(image_path) and (not manual_plate or manual_mileage is None) and not ocr_context
    ocr = _maybe_recognize_vehicle_image(
        image_path if need_ocr else None,
        "用户选择手动输入，未执行自动识别" if not need_ocr else "未上传照片，无法自动识别",
    )

    plate = manual_plate or _normalize_plate(getattr(ocr, "plate", None))
    mileage = manual_mileage if manual_mileage is not None else getattr(ocr, "mileage", None)

    warnings = []
    if ocr_context:
        warnings.extend(_ocr_context_to_warnings(ocr_context, "自动识别结果已由用户确认/修正后保存"))
    elif getattr(ocr, "warnings", None):
        warnings.extend(ocr.warnings)
    if manual_plate:
        warnings.append("车牌号使用了手动输入/确认值")
    if manual_mileage is not None:
        warnings.append("出发里程使用了手动输入/确认值")
    if not need_ocr and (manual_plate or manual_mileage is not None) and not ocr_context:
        warnings.append("本次提交未强制OCR识别")

    if not plate:
        raise ValueError("请填写车牌号，或上传照片让系统自动识别后确认。")
    if mileage is None:
        raise ValueError("请填写出发里程，或上传照片让系统自动识别后确认。")

    start_time = now_str()
    if image_path:
        image_path = rename_trip_photo(image_path, username, plate, start_time)

    lat_f = clean_float(lat)
    lng_f = clean_float(lng)
    address = format_location(lat_f, lng_f)

    data = {
        "username": username,
        "plate": plate,
        "date": today_str(),
        "start_mileage": int(mileage),
        "start_photo": image_path,
        "start_time": start_time,
        "start_lat": lat_f,
        "start_lng": lng_f,
        "start_address": address,
        "start_ocr_text": (ocr_context or {}).get("raw_text", getattr(ocr, "raw_text", "")),
        "start_ocr_conf": (ocr_context or {}).get("confidence", getattr(ocr, "confidence", 0.0)),
        "warning": _join_warnings(warnings),
    }
    trip_id = create_start_trip(data)
    data["id"] = trip_id
    return data


def finish_running_trip(username: str, trip_id: int, image_path: Optional[str], lat, lng, mileage_override=None, ocr_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    回场登记：回场里程手动输入/确认值优先。

    - 填写回场里程：直接保存，不强制 OCR；
    - 未填写回场里程但上传照片：先自动识别并进入确认页；
    - 确认页提交后，以用户确认/修改后的回场里程入库。
    """
    trip = get_trip_by_id(trip_id, username)
    if not trip:
        raise ValueError("未找到当前用户对应的行程")
    if trip.get("status") != "未回场":
        raise ValueError("该行程已经回场，不能重复提交")

    manual_mileage = _manual_int(mileage_override)
    need_ocr = bool(image_path) and manual_mileage is None and not ocr_context
    ocr = _maybe_recognize_vehicle_image(
        image_path if need_ocr else None,
        "用户选择手动输入，未执行自动识别" if not need_ocr else "未上传照片，无法自动识别",
    )

    end_mileage = manual_mileage if manual_mileage is not None else getattr(ocr, "mileage", None)

    warnings = list(filter(None, [trip.get("warning")]))
    if ocr_context:
        warnings.extend(_ocr_context_to_warnings(ocr_context, "自动识别结果已由用户确认/修正后保存"))
    elif getattr(ocr, "warnings", None):
        warnings.extend(ocr.warnings)
    if manual_mileage is not None:
        warnings.append("回场里程使用了手动输入/确认值")
    if not need_ocr and manual_mileage is not None and not ocr_context:
        warnings.append("本次提交未强制OCR识别")

    if end_mileage is None:
        raise ValueError("请填写回场里程，或上传照片让系统自动识别后确认。")

    calc = calculate_distance(int(trip["start_mileage"]), int(end_mileage))
    warnings.extend(calc["warnings"])

    end_time = now_str()
    if image_path:
        image_path = rename_trip_photo(image_path, username, trip.get("plate") or getattr(ocr, "plate", None) or "plate", end_time)

    lat_f = clean_float(lat)
    lng_f = clean_float(lng)
    address = format_location(lat_f, lng_f)

    data = {
        "trip_id": trip_id,
        "end_mileage": int(end_mileage),
        "end_photo": image_path,
        "end_time": end_time,
        "end_lat": lat_f,
        "end_lng": lng_f,
        "end_address": address,
        "distance": int(calc["distance"]) if calc["distance"] is not None else None,
        "end_ocr_text": (ocr_context or {}).get("raw_text", getattr(ocr, "raw_text", "")),
        "end_ocr_conf": (ocr_context or {}).get("confidence", getattr(ocr, "confidence", 0.0)),
        "warning": _join_warnings(warnings),
    }
    dao_finish_trip(data)
    result = dict(trip)
    result.update(data)
    result["status"] = "已完成"
    return result
