from __future__ import annotations

import ipaddress
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from ios_wifi_loc.coords import CoordError
from ios_wifi_loc.geo import to_wgs84

class ShareLinkError(ValueError):
    pass


ALLOWED_HOST_SUFFIXES = (
    "amap.com",
    "autonavi.com",
    "google.com",
    "google.com.hk",
    "google.co.jp",
    "goo.gl",
    "g.page",
    "apple.com",
    "icloud.com",
    "baidu.com",
    "qq.com",
    "tencent.com",
)

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_PAIR = re.compile(r"(-?\d{1,3}\.\d+)\s*[,，\s]\s*(-?\d{1,3}\.\d+)")
USER_AGENT = "ios-wifi-loc/0.4.1 (+lan-shortcut)"
MAX_BODY = 64 * 1024
DEFAULT_TIMEOUT = 3.0
MAX_REDIRECTS = 5


def infer_system(text: str, explicit: str | None = None) -> str:
    if explicit:
        from ios_wifi_loc.geo import normalize_system

        return normalize_system(explicit)
    raw = (text or "").lower()
    if any(token in raw for token in ("baidu.com", "map.baidu", "j.map.baidu", "bd09", "百度地图")):
        return "bd09"
    if any(token in raw for token in ("amap.com", "autonavi", "gaode", "高德", "map.qq.com", "qq.com/map", "腾讯地图")):
        return "gcj02"
    return "wgs84"


def _host_allowed(host: str) -> bool:
    host = (host or "").split("%", 1)[0].strip(".").lower()
    if not host or host == "localhost":
        return False
    if host.endswith(ALLOWED_HOST_SUFFIXES):
        return True
    # maps.app.goo.gl, surl.amap.com already covered by suffixes goo.gl / amap.com
    return False


def _is_private_host(host: str) -> bool:
    host = (host or "").split("%", 1)[0]
    if not host:
        return True
    if host.lower() in {"localhost", "metadata.google.internal"}:
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


def _swap_if_needed(first: float, second: float) -> tuple[float, float]:
    # If the first number looks like longitude, swap.
    if abs(first) > 90 and abs(second) <= 90:
        return second, first
    return first, second


def _pairs_from_text(text: str) -> list[tuple[float, float]]:
    found: list[tuple[float, float]] = []
    for match in _PAIR.finditer(text or ""):
        try:
            a = float(match.group(1))
            b = float(match.group(2))
        except ValueError:
            continue
        if abs(a) <= 180 and abs(b) <= 180:
            found.append(_swap_if_needed(a, b))
    return found


def parse_coords_from_text(text: str, *, system: str | None = None) -> dict | None:
    raw = unquote(text or "")
    kind = infer_system(raw, system)
    # Named query parameters first.
    try:
        parsed = urlparse(raw if "://" in raw else "https://placeholder.invalid/?" + raw)
        query = parse_qs(parsed.query, keep_blank_values=False)
        # Also parse fragment (Google / Apple sometimes put @lat,lon there)
        blob = raw + "&" + (parsed.fragment or "")
    except ValueError:
        query, blob = {}, raw

    def take(*keys: str) -> str | None:
        for key in keys:
            values = query.get(key)
            if values and values[0].strip():
                return values[0].strip()
        return None

    lat_s = take("lat", "latitude", "pointy", "y")
    lon_s = take("lon", "lng", "longitude", "pointx", "x")
    if lat_s and lon_s:
        try:
            wlat, wlon, source = to_wgs84(float(lat_s), float(lon_s), kind)
            return {"latitude": wlat, "longitude": wlon, "system": source, "raw_system": kind}
        except (CoordError, ValueError):
            pass

    for key in ("ll", "sll", "q", "coordinate", "center", "daddr", "saddr", "location", "pos", "position", "mlatlon"):
        values = query.get(key) or []
        for value in values:
            cleaned = value.replace("%2C", ",").replace("%2c", ",")
            pairs = _pairs_from_text(cleaned)
            if pairs:
                lat, lon = pairs[0]
                # Amap position=lon,lat (first often > 90 after swap already handled)
                # Baidu location=lat,lng typically
                if key == "position" and abs(float(cleaned.split(",")[0])) <= 180:
                    parts = [p.strip() for p in cleaned.replace("，", ",").split(",") if p.strip()]
                    if len(parts) >= 2:
                        try:
                            first, second = float(parts[0]), float(parts[1])
                            if abs(first) > 90 or (abs(first) <= 180 and abs(second) <= 90 and abs(first) > abs(second) and abs(first) > 60):
                                lon, lat = first, second
                            else:
                                lat, lon = _swap_if_needed(first, second)
                        except ValueError:
                            lat, lon = pairs[0]
                try:
                    wlat, wlon, source = to_wgs84(lat, lon, kind)
                    return {"latitude": wlat, "longitude": wlon, "system": source, "raw_system": kind}
                except (CoordError, ValueError):
                    continue

    # Apple / Google @lat,lon and !3dlat!4dlon
    for pattern in (
        re.compile(r"@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)"),
        re.compile(r"!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)"),
        re.compile(r"[?&](?:ll|sll|q|coordinate|center)=(-?\d{1,3}\.\d+)(?:,|%2[Cc])(-?\d{1,3}\.\d+)", re.I),
        re.compile(r"position=((-?\d{1,3}\.\d+)(?:,|%2[Cc])(-?\d{1,3}\.\d+))", re.I),
    ):
        match = pattern.search(blob)
        if not match:
            continue
        if match.lastindex and match.lastindex >= 2:
            if pattern.pattern.startswith("position"):
                first, second = float(match.group(2)), float(match.group(3))
                lat, lon = second, first if abs(first) > 90 or abs(first) > abs(second) else _swap_if_needed(first, second)
                if abs(first) <= 180 and abs(second) <= 90 and abs(first) > 60:
                    lon, lat = first, second
            else:
                lat, lon = _swap_if_needed(float(match.group(1)), float(match.group(2)))
            try:
                wlat, wlon, source = to_wgs84(lat, lon, kind)
                return {"latitude": wlat, "longitude": wlon, "system": source, "raw_system": kind}
            except (CoordError, ValueError):
                continue

    pairs = _pairs_from_text(raw)
    if pairs:
        lat, lon = pairs[0]
        try:
            wlat, wlon, source = to_wgs84(lat, lon, kind)
            return {"latitude": wlat, "longitude": wlon, "system": source, "raw_system": kind}
        except (CoordError, ValueError):
            pass
    return None


def _request(url: str, *, timeout: float, method: str = "GET") -> tuple[str, bytes, str | None]:
    req = Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            final = resp.geturl() or url
            body = resp.read(MAX_BODY + 1)
            return final, body[:MAX_BODY], resp.headers.get("Location")
    except HTTPError as exc:
        location = exc.headers.get("Location") if exc.headers else None
        body = b""
        try:
            body = exc.read(MAX_BODY)
        except Exception:
            body = b""
        return location or url, body, location
    except URLError as exc:
        raise ShareLinkError(f"无法解析短链接：{exc.reason}") from exc


def follow_share_url(url: str, *, timeout: float = DEFAULT_TIMEOUT, fetcher=None) -> str:
    current = url.strip()
    seen: set[str] = set()
    for _ in range(MAX_REDIRECTS + 1):
        if current in seen:
            break
        seen.add(current)
        parsed = urlparse(current)
        if parsed.scheme not in {"http", "https"}:
            raise ShareLinkError("只跟随 http/https 地图链接")
        if not _host_allowed(parsed.hostname or ""):
            # Still return the URL so the caller can parse coords already present.
            return current
        if fetcher is None and _is_private_host(parsed.hostname or ""):
            raise ShareLinkError("拒绝访问非公开地址")
        if fetcher is None:
            final, body, location = _request(current, timeout=timeout)
        else:
            final, body, location = fetcher(current)
        for candidate in (location, final, current):
            if candidate:
                found = parse_coords_from_text(urljoin(current, candidate))
                if found:
                    return urljoin(current, candidate)
        text = ""
        if body:
            text = body.decode("utf-8", "replace")
            # Common meta / canonical / data attributes
            for pattern in (
                re.compile(r'<meta[^>]+content="([^"]+)"', re.I),
                re.compile(r'https?://[^\s"\'<>]+', re.I),
            ):
                for match in pattern.finditer(text):
                    found = parse_coords_from_text(match.group(1) if match.lastindex else match.group(0))
                    if found:
                        return match.group(1) if match.lastindex else match.group(0)
        if final and final != current:
            current = urljoin(current, final)
            continue
        if location:
            current = urljoin(current, location)
            continue
        return current
    return current


def parse_share(text: str, *, system: str | None = None, follow: bool = True, timeout: float = DEFAULT_TIMEOUT, fetcher=None) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ShareLinkError("没有可解析的坐标或地图链接")
    direct = parse_coords_from_text(raw, system=system)
    if direct:
        direct["input"] = raw[:500]
        return direct
    urls = _URL.findall(raw)
    if raw.startswith(("http://", "https://")) and raw not in urls:
        urls.insert(0, raw)
    last_error = "无法从分享内容里解析出坐标"
    for url in urls:
        try:
            resolved = follow_share_url(url, timeout=timeout, fetcher=fetcher) if follow else url
        except ShareLinkError as exc:
            last_error = str(exc)
            resolved = url
        found = parse_coords_from_text(resolved, system=system) or parse_coords_from_text(url, system=system)
        if found:
            found["input"] = raw[:500]
            found["resolved"] = resolved[:500]
            return found
    raise ShareLinkError(last_error)
