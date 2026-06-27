from typing import Optional


def clean_float(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def format_location(lat, lng) -> str:
    lat_f = clean_float(lat)
    lng_f = clean_float(lng)
    if lat_f is None or lng_f is None:
        return "定位失败"
    return f"{lat_f:.6f}, {lng_f:.6f}"
