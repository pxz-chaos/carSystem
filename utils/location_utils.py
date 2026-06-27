"""Location helpers with cached reverse geocoding.

The old implementation returned only "lat,lng".  This version keeps that as a
safe fallback, and optionally resolves a human-readable address through a free
reverse-geocoding endpoint with local SQLite cache and a 1 request/s throttle.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

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


def _cache_key(lat_f: float, lng_f: float) -> str:
    # 5 decimals is roughly meter-level precision and avoids repeated lookups
    # for tiny GPS drift around the same parking spot.
    return f"{lat_f:.5f},{lng_f:.5f}"


def _read_cache(key: str) -> Optional[str]:
    try:
        conn = sqlite3.connect(_cache_path(), timeout=3)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS geocode_cache(key TEXT PRIMARY KEY, address TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
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
        conn.execute(
            "CREATE TABLE IF NOT EXISTS geocode_cache(key TEXT PRIMARY KEY, address TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache(key, address, updated_at) VALUES(?,?,?)",
            (key, address, int(time.time())),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _throttle_upstream() -> None:
    """Best-effort 1 request/s throttle shared across gunicorn threads/processes."""
    path = _cache_path()
    try:
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.execute("CREATE TABLE IF NOT EXISTS geocode_meta(name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM geocode_meta WHERE name='last_request_at'").fetchone()
        now = time.time()
        if row:
            last = float(row[0] or 0)
            delay = 1.05 - (now - last)
            if delay > 0:
                time.sleep(min(delay, 1.2))
        conn.execute(
            "INSERT OR REPLACE INTO geocode_meta(name, value) VALUES('last_request_at', ?)",
            (str(time.time()),),
        )
        conn.commit()
        conn.close()
    except Exception:
        # Never let reverse geocoding block trip submission.
        pass


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
    _throttle_upstream()
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
    key = _cache_key(lat_f, lng_f)
    cached = _read_cache(key)
    if cached:
        return cached
    if not _env_bool("REVERSE_GEOCODE_ENABLED", "1"):
        return None
    provider = os.environ.get("REVERSE_GEOCODE_PROVIDER", "nominatim").strip().lower()
    address = None
    if provider == "nominatim":
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
