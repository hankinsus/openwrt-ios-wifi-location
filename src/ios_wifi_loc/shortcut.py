from __future__ import annotations

from ios_wifi_loc.coords import CoordError
from ios_wifi_loc.geo import pair_to_wgs84
from ios_wifi_loc.identifiers import IdentifierError, validate_udid
from ios_wifi_loc.session import (
    clear_location,
    select_device,
    set_location,
    status,
)
from ios_wifi_loc.sharelinks import ShareLinkError, parse_share
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.tunneld import query_tunneld, tunnel_ready_for


class ShortcutError(ValueError):
    pass


def _names(store: StateStore, udid: str | None) -> dict:
    data = store.load()
    names = data.get("device_names") or {}
    if udid and isinstance(names, dict):
        entry = names.get(udid) or {}
        if isinstance(entry, dict):
            return entry
    return {}


def pick_shortcut_device(store: StateStore, udid: str | None = None) -> dict:
    data = store.load()
    if udid:
        try:
            checked = validate_udid(udid)
        except IdentifierError as exc:
            raise ShortcutError(str(exc)) from exc
    else:
        selected = data.get("selected") or {}
        checked = selected.get("udid") if isinstance(selected, dict) else None
        if not checked:
            tunneld = query_tunneld()
            discovery = list(data.get("discovery") or [])
            sessions = data.get("sessions") or {}
            candidates = []
            for item in discovery:
                if isinstance(item, dict) and item.get("udid"):
                    candidates.append(item)
            for item in (tunneld.get("tunnels") or []):
                if isinstance(item, dict) and item.get("udid"):
                    candidates.append(item)
            for key, sess in (sessions.items() if isinstance(sessions, dict) else []):
                if isinstance(sess, dict):
                    candidates.append({"udid": key, **sess, "alive": sess.get("pid")})
            ready = [item for item in candidates if tunnel_ready_for(item["udid"], tunneld)]
            alive = [item for item in candidates if item.get("session_alive") or item.get("holding") or item.get("alive")]
            chosen = (ready or alive or candidates)
            if not chosen:
                raise ShortcutError("没有可用设备。请先在网页里导入配对文件并选择一台 iPhone。")
            checked = chosen[0]["udid"]
    known = {item["udid"]: item for item in (data.get("discovery") or []) if isinstance(item, dict) and item.get("udid")}
    record = known.get(checked) or {}
    selected = data.get("selected") or {}
    transport = record.get("transport") or (selected.get("transport") if isinstance(selected, dict) and selected.get("udid") == checked else None) or "mobdev2"
    host = record.get("host") or (selected.get("host") if isinstance(selected, dict) and selected.get("udid") == checked else None)
    name = record.get("name") or _names(store, checked).get("name")
    outcome = select_device(
        store,
        udid=checked,
        transport=transport,
        host=host,
        name=name,
        allow_usb=False,
        usbmux_address=None,
    )
    if not outcome.ok:
        raise ShortcutError(outcome.summary)
    return {"udid": checked, "transport": transport, "host": host, "name": name, "product_version": _names(store, checked).get("product_version")}


def resolve_coordinates(params: dict, *, follow: bool = True, fetcher=None) -> dict:
    lat = params.get("lat") or params.get("latitude")
    lon = params.get("lon") or params.get("lng") or params.get("longitude")
    system = params.get("coord") or params.get("system") or params.get("crs")
    text = params.get("text") or params.get("url") or params.get("q") or params.get("u") or params.get("input")
    if lat not in {None, ""} and lon not in {None, ""}:
        wlat, wlon, kind = pair_to_wgs84(str(lat), str(lon), str(system) if system else "wgs84")
        return {"latitude": wlat, "longitude": wlon, "system": kind, "input": None}
    if text:
        parsed = parse_share(str(text), system=str(system) if system else None, follow=follow, fetcher=fetcher)
        return parsed
    raise ShortcutError("请提供 lat/lon，或分享高德 / 百度 / 苹果 / 谷歌地图链接，或纯坐标文本")


def format_shortcut_status(store: StateStore, *, udid: str | None = None) -> dict:
    current = status(store)
    data = dict(current.details)
    target = udid or ((data.get("selected") or {}) or {}).get("udid")
    sessions = {item.get("udid"): item for item in (data.get("sessions") or []) if isinstance(item, dict)}
    session = sessions.get(target) if target else data.get("session")
    meta = _names(store, target)
    name = meta.get("name") or (data.get("selected") or {}).get("name") or target or "未选择设备"
    if session and (session.get("alive") or session.get("holding")):
        line = f"{name} 正在模拟 {session.get('latitude')}, {session.get('longitude')}"
        if session.get("watchdog_active"):
            line += f"（自动重连已开启，已重连 {session.get('reconnect_count') or 0} 次）"
        if session.get("waiting_reconnect"):
            line += "，等待隧道恢复自动重连…"
        code = "HOLDING"
    else:
        line = f"{name} 当前没有模拟定位"
        code = "IDLE"
    return {
        "ok": True,
        "code": code,
        "summary": line,
        "udid": target,
        "name": name,
        "session": session,
        "text": line,
    }


def shortcut_set(
    store: StateStore,
    binary: str,
    params: dict,
    *,
    timeout: float,
    grace: float,
    follow: bool = True,
    fetcher=None,
) -> dict:
    coords = resolve_coordinates(params, follow=follow, fetcher=fetcher)
    target = pick_shortcut_device(store, params.get("udid") or params.get("device"))
    profile = str(params.get("profile") or "ios17")
    outcome = set_location(
        store,
        binary,
        latitude=coords["latitude"],
        longitude=coords["longitude"],
        profile=profile,
        timeout=timeout,
        grace=grace,
        foreground=False,
        allow_usb=False,
        allow_legacy=False,
        replace=True,
    )
    name = target.get("name") or _names(store, target["udid"]).get("name") or target["udid"]
    if outcome.ok:
        summary = f"已设置 {coords['latitude']}, {coords['longitude']}（WGS-84）到 {name}"
    else:
        summary = outcome.summary
    return {
        "ok": outcome.ok,
        "code": outcome.code,
        "summary": summary,
        "text": summary,
        "latitude": coords["latitude"],
        "longitude": coords["longitude"],
        "system": coords.get("system"),
        "udid": target["udid"],
        "name": name,
        "details": outcome.details,
    }


def shortcut_clear(
    store: StateStore,
    binary: str,
    params: dict,
    *,
    timeout: float,
) -> dict:
    target = pick_shortcut_device(store, params.get("udid") or params.get("device"))
    outcome = clear_location(
        store,
        binary,
        timeout=timeout,
        allow_usb=False,
        profile=str(params.get("profile") or "ios17"),
    )
    name = target.get("name") or _names(store, target["udid"]).get("name") or target["udid"]
    if outcome.ok:
        summary = f"已请求恢复 {name} 的真实定位，请在手机上确认"
    else:
        summary = outcome.summary
    return {
        "ok": outcome.ok,
        "code": outcome.code,
        "summary": summary,
        "text": summary,
        "udid": target["udid"],
        "name": name,
        "details": outcome.details,
    }
