from __future__ import annotations

import json

from ios_wifi_loc.identifiers import IdentifierError, validate_host, validate_udid
from ios_wifi_loc.runner import CommandResult, run
from ios_wifi_loc.tunneld import query_tunneld
from ios_wifi_loc.upstream import bonjour_argv, remote_browse_argv, usbmux_list_argv


def parse_simple_udids(text: str) -> list[str]:
    try:
        value = json.loads(text.strip() or "null")
    except json.JSONDecodeError as exc:
        raise ValueError("上游输出不是 JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("上游输出不是 UDID 字符串列表")
    parsed: list[str] = []
    for item in value:
        try:
            parsed.append(validate_udid(item))
        except IdentifierError as exc:
            raise ValueError("列表中的标识不符合 UDID 规则") from exc
    return parsed


def _as_udid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return validate_udid(value)
    except IdentifierError:
        return None


def _as_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _host_from(item: dict) -> str | None:
    for key in ("ip", "hostname", "host", "address"):
        text = _as_text(item.get(key))
        if text:
            return text
    for key in ("addresses", "ips", "Interfaces", "interfaces"):
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str) and entry.strip():
                    return entry.strip()
                if isinstance(entry, dict):
                    for sub in ("ip", "address", "host", "hostname"):
                        text = _as_text(entry.get(sub))
                        if text:
                            return text
        elif isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_host(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return validate_host(value)
    except IdentifierError:
        # Keep the raw address for display if it is a plausible IPv6/IPv4 token.
        if any(ch in value for ch in " \t\r\n;|&$`<>\\"):
            return None
        return value


def parse_device_records(text: str, *, source: str, connection: str, transport: str) -> list[dict]:
    try:
        value = json.loads(text.strip() or "null")
    except json.JSONDecodeError as exc:
        raise ValueError("上游输出不是 JSON") from exc
    items: list[object]
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        if isinstance(value.get("devices"), list):
            items = value["devices"]
        elif all(_as_udid(key) for key in value.keys()):
            items = [{"udid": key, **(val if isinstance(val, dict) else {})} for key, val in value.items()]
        else:
            items = [value]
    else:
        raise ValueError("上游输出不是设备列表")
    devices: list[dict] = []
    for item in items:
        if isinstance(item, str):
            udid = _as_udid(item)
            if not udid:
                raise ValueError("列表中的标识不符合 UDID 规则")
            devices.append(_record(udid, source=source, connection=connection, transport=transport))
            continue
        if not isinstance(item, dict):
            raise ValueError("上游输出不是设备列表")
        udid = _as_udid(
            item.get("UniqueDeviceID")
            or item.get("uniqueDeviceID")
            or item.get("udid")
            or item.get("UDID")
            or item.get("Identifier")
            or item.get("identifier")
        )
        if not udid:
            raise ValueError("列表中的标识不符合 UDID 规则")
        devices.append(
            _record(
                udid,
                source=source,
                connection=connection,
                transport=transport,
                name=_as_text(item.get("DeviceName") or item.get("name") or item.get("deviceName")),
                product_version=_as_text(item.get("ProductVersion") or item.get("product_version")),
                product_type=_as_text(item.get("ProductType") or item.get("product_type")),
                host=_safe_host(_host_from(item)),
            )
        )
    return devices


def _record(
    udid: str,
    *,
    source: str,
    connection: str,
    transport: str,
    name: str | None = None,
    product_version: str | None = None,
    product_type: str | None = None,
    host: str | None = None,
    tunnel_ready: bool = False,
) -> dict:
    return {
        "udid": udid,
        "connection": connection,
        "transport": transport,
        "source": source,
        "host": host,
        "name": name,
        "product_version": product_version,
        "product_type": product_type,
        "tunnel_ready": tunnel_ready,
    }


def merge_devices(*groups: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for group in groups:
        for item in group:
            udid = item.get("udid")
            if not isinstance(udid, str):
                continue
            if udid not in merged:
                merged[udid] = dict(item)
                order.append(udid)
                continue
            current = merged[udid]
            for key in ("name", "product_version", "product_type", "host", "transport", "connection", "source"):
                if not current.get(key) and item.get(key):
                    current[key] = item[key]
            if item.get("tunnel_ready"):
                current["tunnel_ready"] = True
            if item.get("connection") == "usb" and current.get("connection") != "wifi":
                current["connection"] = "usb"
            if item.get("connection") == "wifi":
                current["connection"] = "wifi"
    return [merged[udid] for udid in order]


def _probe(name: str, argv: list[str], timeout: float, *, connection: str, transport: str, rich: bool) -> dict:
    result = run(argv, timeout=timeout)
    record: dict = {
        "name": name,
        "argv": result.argv[1:],
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "error": result.error,
        "stderr_excerpt": result.stderr[-500:],
        "devices": [],
        "parse_error": None,
    }
    if not result.ok:
        record["unparsed_excerpt"] = result.stdout[:500]
        return record
    try:
        if rich:
            devices = parse_device_records(result.stdout, source=name, connection=connection, transport=transport)
        else:
            devices = [
                _record(udid, source=name, connection=connection, transport=transport)
                for udid in parse_simple_udids(result.stdout)
            ]
    except ValueError as exc:
        record["parse_error"] = str(exc)
        record["unparsed_excerpt"] = result.stdout[:500]
        return record
    record["devices"] = devices
    return record


def discover(binary: str, *, timeout: float, tunneld: dict | None = None) -> dict:
    bounded = max(1.0, min(timeout, 30.0))
    browse_timeout = max(1, min(int(bounded), 30))
    probes = [
        _probe("usbmux_network", usbmux_list_argv(binary, kind="network"), bounded, connection="wifi", transport="usbmux", rich=False),
        _probe("usbmux_usb", usbmux_list_argv(binary, kind="usb"), bounded, connection="usb", transport="usbmux", rich=False),
        _probe("bonjour_mobdev2", bonjour_argv(binary), bounded, connection="wifi", transport="mobdev2", rich=True),
        _probe("remote_browse", remote_browse_argv(binary, browse_timeout), bounded + 2, connection="wifi", transport="remotepairing", rich=True),
    ]
    tunnel_info = tunneld if tunneld is not None else query_tunneld()
    tunnel_devices = []
    for item in tunnel_info.get("tunnels") or []:
        udid = item.get("udid")
        if not isinstance(udid, str):
            continue
        tunnel_devices.append(
            _record(
                udid,
                source="tunneld",
                connection="wifi",
                transport="mobdev2",
                host=_safe_host(item.get("address") or item.get("interface")),
                tunnel_ready=True,
            )
        )
    devices = merge_devices(*[probe["devices"] for probe in probes], tunnel_devices)
    if tunnel_info.get("reachable"):
        ready = {item["udid"] for item in tunnel_devices}
        # If tunneld is up but has not yet published a UDID, still mark known Wi-Fi devices as pending.
        for item in devices:
            if item["udid"] in ready:
                item["tunnel_ready"] = True
    return {"probes": probes, "devices": devices, "tunneld": tunnel_info}


def command_failed(result: CommandResult) -> str:
    if result.error == "binary_missing":
        return "找不到上游可执行文件"
    if result.error and result.error.startswith("os_error"):
        return "上游进程无法启动"
    if result.timed_out:
        return "上游命令超时"
    return f"上游命令退出码为 {result.returncode}"
