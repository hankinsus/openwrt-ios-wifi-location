from __future__ import annotations

import math

from ios_wifi_loc.coords import CoordError, canonical, parse_pair

_A = 6378245.0
_EE = 0.00669342162296594323
_PI = math.pi


def out_of_china(lat: float, lon: float) -> bool:
    return lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320.0 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def _delta(lat: float, lon: float) -> tuple[float, float]:
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * _PI
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(rad) * _PI)
    return dlat, dlon


def wgs_to_gcj(lat: float, lon: float) -> tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon
    dlat, dlon = _delta(lat, lon)
    return lat + dlat, lon + dlon


def gcj_to_wgs(lat: float, lon: float) -> tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon
    wlat, wlon = lat, lon
    for _ in range(8):
        glat, glon = wgs_to_gcj(wlat, wlon)
        wlat -= glat - lat
        wlon -= glon - lon
    return wlat, wlon


def bd09_to_gcj(lat: float, lon: float) -> tuple[float, float]:
    x = lon - 0.0065
    y = lat - 0.006
    z = math.hypot(x, y) - 0.00002 * math.sin(y * _PI * 3000.0 / 180.0)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _PI * 3000.0 / 180.0)
    return z * math.sin(theta), z * math.cos(theta)


def gcj_to_bd09(lat: float, lon: float) -> tuple[float, float]:
    z = math.hypot(lon, lat) + 0.00002 * math.sin(lat * _PI * 3000.0 / 180.0)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * _PI * 3000.0 / 180.0)
    return z * math.sin(theta) + 0.006, z * math.cos(theta) + 0.0065


def bd09_to_wgs(lat: float, lon: float) -> tuple[float, float]:
    return gcj_to_wgs(*bd09_to_gcj(lat, lon))


def normalize_system(value: str | None) -> str:
    raw = (value or "wgs84").strip().lower().replace("-", "").replace("_", "")
    if raw in {"wgs84", "wgs", "apple", "google"}:
        return "wgs84"
    if raw in {"gcj02", "gcj", "amap", "gaode", "autonavi", "tencent", "qq"}:
        return "gcj02"
    if raw in {"bd09", "bd09ll", "baidu", "bd"}:
        return "bd09"
    raise CoordError("坐标系只能是 wgs84、gcj02 或 bd09")


def to_wgs84(lat: float, lon: float, system: str | None = "wgs84") -> tuple[str, str, str]:
    kind = normalize_system(system)
    if kind == "gcj02":
        lat, lon = gcj_to_wgs(lat, lon)
    elif kind == "bd09":
        lat, lon = bd09_to_wgs(lat, lon)
    parsed = parse_pair(f"{lat:.8f}", f"{lon:.8f}")
    return parsed[0], parsed[1], kind


def pair_to_wgs84(latitude: str, longitude: str, system: str | None = "wgs84") -> tuple[str, str, str]:
    lat, lon = parse_pair(latitude, longitude)
    return to_wgs84(float(lat), float(lon), system)
