"""Location helpers with cached reverse geocoding.

手机浏览器只能直接拿到经纬度；本模块负责把经纬度反查成人可读地址。

推荐在中国大陆使用高德 Web 服务逆地理编码：
    REVERSE_GEOCODE_PROVIDER=amap
    AMAP_WEB_SERVICE_KEY=你的高德Web服务Key

如果未配置高德 Key，则会尝试 Nominatim；失败时安全退回到 "lat,lng"，
保证司机提交行程不会因为外部地图接口异常而失败。
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
from typing import Optional, Tuple

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - requests may be absent before pip install
    requests = None  # type: ignore

try:
    from config import BASE_DIR  # type: ignore
except Exception:  # pragma: no cover
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return int(default)


def clean_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _coord_text(lat_f: float, lng_f: float) -> str:
    return f"{lat_f:.6f}, {lng_f:.6f}"


def _cache_path() -> str:
    path = os.environ.get(
        "REVERSE_GEOCODE_CACHE_PATH",
        os.path.join(BASE_DIR, "database", "reverse_geocode_cache.sqlite3"),
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return path


def _provider_cache_key(provider: str, lat_f: float, lng_f: float) -> str:
    # 5 decimals is roughly meter-level precision and avoids repeated lookups
    # for tiny GPS drift around the same parking spot.
    return f"{provider}:{lat_f:.5f},{lng_f:.5f}"


def _ensure_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS geocode_cache(key TEXT PRIMARY KEY, address TEXT NOT NULL, updated_at INTEGER NOT NULL)"
    )


def _read_cache(key: str) -> Optional[str]:
    try:
        conn = sqlite3.connect(_cache_path(), timeout=3)
        _ensure_cache_table(conn)
        row = conn.execute("SELECT address FROM geocode_cache WHERE key=?", (key,)).fetchone()
        conn.close()
        if row and row[0]:
            return str(row[0])
    except Exception:
        return None
    return None


def _write_cache(key: str, address: str) -> None:
    try:
        conn = sqlite3.connect(_cache_path(), timeout=3)
        _ensure_cache_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache(key, address, updated_at) VALUES(?,?,?)",
            (key, address, int(time.time())),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _throttle_upstream(provider: str, min_interval_seconds: float = 1.05) -> None:
    """Best-effort throttle shared across gunicorn threads/processes."""
    path = _cache_path()
    try:
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.execute("CREATE TABLE IF NOT EXISTS geocode_meta(name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        name = f"last_request_at:{provider}"
        row = conn.execute("SELECT value FROM geocode_meta WHERE name=?", (name,)).fetchone()
        now = time.time()
        if row:
            last = float(row[0] or 0)
            delay = min_interval_seconds - (now - last)
            if delay > 0:
                time.sleep(min(delay, min_interval_seconds + 0.2))
        conn.execute(
            "INSERT OR REPLACE INTO geocode_meta(name, value) VALUES(?, ?)",
            (name, str(time.time())),
        )
        conn.commit()
        conn.close()
    except Exception:
        # Never let reverse geocoding block trip submission.
        pass


# WGS84 -> GCJ-02 conversion for AMap in mainland China.
# Browser Geolocation usually returns WGS84. 高德 Web 服务使用高德坐标系，
# 不转换会有几十到几百米偏移，可能影响附近 POI 名称。
_X_PI = math.pi * 3000.0 / 180.0
_PI = math.pi
_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lat: float, lng: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> Tuple[float, float]:
    if _out_of_china(lat, lng):
        return lat, lng
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lat + dlat, lng + dlng


def _shorten_amap_address(data: dict) -> Optional[str]:
    regeocode = data.get("regeocode") or {}
    formatted = str(regeocode.get("formatted_address") or "").strip()
    if not formatted:
        return None

    # 有 POI 时拼一个更像“具体地点”的文本：完整地址（附近：某某，约xx米）
    pois = regeocode.get("pois") or []
    if isinstance(pois, list) and pois:
        poi = pois[0] or {}
        name = str(poi.get("name") or "").strip()
        distance = str(poi.get("distance") or "").strip()
        if name and name not in formatted:
            if distance and distance.isdigit():
                return f"{formatted}（附近：{name}，约{distance}米）"[:300]
            return f"{formatted}（附近：{name}）"[:300]
    return formatted[:300]


def _amap_reverse(lat_f: float, lng_f: float) -> Optional[str]:
    if requests is None:
        return None
    key = os.environ.get("AMAP_WEB_SERVICE_KEY", "").strip() or os.environ.get("AMAP_KEY", "").strip()
    if not key:
        return None

    # 默认把浏览器 WGS84 坐标转换成高德 GCJ-02 坐标。若你前端已经使用高德定位，设 AMAP_INPUT_COORD_TYPE=gcj02。
    coord_type = os.environ.get("AMAP_INPUT_COORD_TYPE", "wgs84").strip().lower()
    amap_lat, amap_lng = (lat_f, lng_f)
    if coord_type in {"wgs84", "gps"} and _env_bool("AMAP_WGS84_TO_GCJ02", "1"):
        amap_lat, amap_lng = wgs84_to_gcj02(lat_f, lng_f)

    endpoint = os.environ.get("AMAP_REVERSE_ENDPOINT", "https://restapi.amap.com/v3/geocode/regeo").strip()
    timeout = _env_int("REVERSE_GEOCODE_TIMEOUT_SECONDS", "3")
    params = {
        "key": key,
        "location": f"{amap_lng:.6f},{amap_lat:.6f}",  # 高德要求：经度在前，纬度在后
        "output": "JSON",
        "extensions": os.environ.get("AMAP_REVERSE_EXTENSIONS", "all"),
        "radius": os.environ.get("AMAP_REVERSE_RADIUS", "1000"),
    }
    _throttle_upstream("amap", 0.05)
    try:
        resp = requests.get(endpoint, params=params, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if str(data.get("status")) != "1":
            return None
        return _shorten_amap_address(data)
    except Exception:
        return None


def _nominatim_reverse(lat_f: float, lng_f: float) -> Optional[str]:
    if requests is None:
        return None
    endpoint = os.environ.get("NOMINATIM_ENDPOINT", "https://nominatim.openstreetmap.org/reverse").strip()
    user_agent = os.environ.get("NOMINATIM_USER_AGENT", "CarFleetSystem/1.0 (admin@example.com)").strip()
    email = os.environ.get("NOMINATIM_EMAIL", "").strip()
    timeout = _env_int("REVERSE_GEOCODE_TIMEOUT_SECONDS", "3")
    params = {
        "format": "jsonv2",
        "lat": f"{lat_f:.6f}",
        "lon": f"{lng_f:.6f}",
        "zoom": os.environ.get("REVERSE_GEOCODE_ZOOM", "18"),
        "addressdetails": "1",
        "accept-language": os.environ.get("REVERSE_GEOCODE_LANGUAGE", "zh-CN,zh,en"),
    }
    if email:
        params["email"] = email
    countrycodes = os.environ.get("REVERSE_GEOCODE_COUNTRYCODES", "cn").strip()
    if countrycodes:
        params["countrycodes"] = countrycodes
    headers = {"User-Agent": user_agent}
    _throttle_upstream("nominatim", 1.05)
    try:
        resp = requests.get(endpoint, params=params, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        data = resp.json()
        address = str(data.get("display_name") or "").strip()
        if address:
            return address[:300]
    except Exception:
        return None
    return None


def reverse_geocode(lat, lng) -> Optional[str]:
    lat_f = clean_float(lat)
    lng_f = clean_float(lng)
    if lat_f is None or lng_f is None:
        return None
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return None
    if not _env_bool("REVERSE_GEOCODE_ENABLED", "1"):
        return None

    provider = os.environ.get("REVERSE_GEOCODE_PROVIDER", "auto").strip().lower()
    providers = []
    if provider in {"auto", ""}:
        # 国内优先高德；没有 Key 时再尝试 Nominatim。
        if os.environ.get("AMAP_WEB_SERVICE_KEY") or os.environ.get("AMAP_KEY"):
            providers.append("amap")
        providers.append("nominatim")
    elif provider in {"amap", "gaode", "amap_web"}:
        providers.append("amap")
        if _env_bool("REVERSE_GEOCODE_FALLBACK_NOMINATIM", "0"):
            providers.append("nominatim")
    elif provider == "nominatim":
        providers.append("nominatim")
    else:
        providers.append(provider)

    for p in providers:
        key = _provider_cache_key(p, lat_f, lng_f)
        cached = _read_cache(key)
        if cached:
            return cached

        address = None
        if p in {"amap", "gaode", "amap_web"}:
            address = _amap_reverse(lat_f, lng_f)
        elif p == "nominatim":
            address = _nominatim_reverse(lat_f, lng_f)

        if address:
            _write_cache(key, address)
            return address
    return None


def format_location(lat, lng) -> str:
    lat_f = clean_float(lat)
    lng_f = clean_float(lng)
    if lat_f is None or lng_f is None:
        return "定位失败"
    address = reverse_geocode(lat_f, lng_f)
    if address:
        return address
    return _coord_text(lat_f, lng_f)
