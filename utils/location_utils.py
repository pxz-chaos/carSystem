from functools import lru_cache
import json
from typing import Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def clean_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _coord_text(lat_f: float, lng_f: float) -> str:
    return f"{lat_f:.6f}, {lng_f:.6f}"


def _pick_first(address: Dict[str, str], keys) -> str:
    for key in keys:
        value = str(address.get(key) or "").strip()
        if value:
            return value
    return ""


@lru_cache(maxsize=512)
def _reverse_geocode_nominatim(lat_key: float, lng_key: float) -> str:
    """
    经纬度反查城市/区县。
    使用公开 Nominatim 服务；网络不可用、服务不可达或返回不完整时自动回退到经纬度。
    """
    query = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{lat_key:.6f}",
            "lon": f"{lng_key:.6f}",
            "zoom": "14",
            "addressdetails": "1",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.5",
        }
    )
    req = Request(
        "https://nominatim.openstreetmap.org/reverse?" + query,
        headers={
            "User-Agent": "CarManagementSystem/1.0 (local enterprise fleet app)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=4) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return ""

    address = payload.get("address") or {}
    if not isinstance(address, dict):
        return ""

    province = _pick_first(address, ["state", "province", "region"])
    city = _pick_first(address, ["city", "town", "county", "municipality"])
    district = _pick_first(address, ["city_district", "district", "borough", "suburb", "county"])

    parts = []
    for part in [province, city, district]:
        if part and part not in parts:
            parts.append(part)

    return " ".join(parts)


def format_location(lat, lng) -> str:
    lat_f = clean_float(lat)
    lng_f = clean_float(lng)
    if lat_f is None or lng_f is None:
        return "定位失败"

    coord = _coord_text(lat_f, lng_f)
    # 缓存时四舍五入到 5 位小数，减少同一区域重复反查；显示仍保留原始精度。
    address = _reverse_geocode_nominatim(round(lat_f, 5), round(lng_f, 5))
    if address:
        return f"{address}（{coord}）"
    return coord
