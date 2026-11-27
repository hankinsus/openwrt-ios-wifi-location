from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ios_wifi_loc.identifiers import IdentifierError, validate_udid
from ios_wifi_loc.upstream import executable

DEFAULT_TUNNELD_URL = "http://127.0.0.1:49151/"
DEFAULT_TIMEOUT = 1.5


def tunneld_url() -> str:
    return os.environ.get("IOS_WIFI_LOC_TUNNELD_URL") or DEFAULT_TUNNELD_URL


def tunneld_argv(binary: str) -> list[str]:
    return [
        executable(binary),
        "remote",
        "tunneld",
        "--protocol",
        "tcp",
        "--no-usb",
        "--no-usbmux",
        "--mobdev2",
    ]


def parse_tunneld_payload(data: Any) -> list[dict]:
    if isinstance(data, dict) and "tunnels" in data and not _looks_like_udid(next(iter(data), "")):
        return parse_tunneld_payload(data.get("tunnels"))
    if isinstance(data, dict) and "devices" in data and isinstance(data["devices"], list):
        return parse_tunneld_payload(data["devices"])
    tunnels: list[dict] = []
    if isinstance(data, list):
        for item in data:
            parsed = _entry(None, item)
            if parsed:
                tunnels.append(parsed)
        return _dedupe(tunnels)
    if not isinstance(data, dict):
        return []
    for key, value in data.items():
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                for item in value:
                    parsed = _entry(key, item)
                    if parsed:
                        tunnels.append(parsed)
            else:
                parsed = _entry(key, value)
                if parsed:
                    tunnels.append(parsed)
        else:
            parsed = _entry(key, value)
            if parsed:
                tunnels.append(parsed)
    return _dedupe(tunnels)


def _looks_like_udid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        validate_udid(value)
        return True
    except IdentifierError:
        return False


def _as_udid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return validate_udid(value)
    except IdentifierError:
        return None


def _entry(key: str | None, value: Any) -> dict | None:
    udid = _as_udid(key)
    address = None
    port = None
    interface = None
    if isinstance(value, dict):
        udid = _as_udid(value.get("udid") or value.get("UniqueDeviceID") or value.get("identifier") or key) or udid
        address = _as_str(
            value.get("tunnel-address")
            or value.get("address")
            or value.get("host")
            or value.get("interface")
            or value.get("rsd-address")
        )
        port = _as_port(value.get("tunnel-port") or value.get("port") or value.get("Port"))
        interface = _as_str(value.get("interface"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        address = _as_str(value[0])
        port = _as_port(value[1])
    if not udid:
        return None
    return {"udid": udid, "address": address, "port": port, "interface": interface}


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _as_port(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _dedupe(tunnels: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in tunnels:
        seen.setdefault(item["udid"], item)
    return list(seen.values())


def query_tunneld(url: str | None = None, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    target = url or tunneld_url()
    result: dict = {"reachable": False, "url": target, "tunnels": [], "error": None}
    try:
        request = urllib.request.Request(target, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024)
        data = json.loads(raw.decode("utf-8"))
        result["reachable"] = True
        result["tunnels"] = parse_tunneld_payload(data)
    except urllib.error.HTTPError as exc:
        result["error"] = f"http_{exc.code}"
    except urllib.error.URLError:
        result["error"] = "unreachable"
    except TimeoutError:
        result["error"] = "timeout"
    except json.JSONDecodeError:
        result["error"] = "invalid_json"
    except OSError:
        result["error"] = "unreachable"
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        result["error"] = type(exc).__name__
    return result


def tunnel_endpoint_for(udid: str, status: dict | None = None) -> dict | None:
    """Return the listed tunnel for this UDID, or None if missing or tunneld is down."""
    info = status if status is not None else query_tunneld()
    if not info.get("reachable"):
        return None
    try:
        checked = validate_udid(udid)
    except IdentifierError:
        return None
    for item in info.get("tunnels") or []:
        if item.get("udid") == checked:
            return {
                "address": item.get("address"),
                "port": item.get("port"),
                "interface": item.get("interface"),
                "reachable": True,
            }
    return None


def tunnel_signature(endpoint: dict | None) -> tuple[object, object] | None:
    if not endpoint:
        return None
    return (endpoint.get("address"), endpoint.get("port"))


def tunnel_ready_for(udid: str, status: dict | None = None) -> bool:
    info = status if status is not None else query_tunneld()
    if not info.get("reachable"):
        return False
    try:
        checked = validate_udid(udid)
    except IdentifierError:
        return False
    tunnels = info.get("tunnels") or []
    if not tunnels:
        # tunneld is up and may create the tunnel on demand for --tunnel
        return True
    return any(item.get("udid") == checked for item in tunnels)
