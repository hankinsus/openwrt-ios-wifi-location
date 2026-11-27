from __future__ import annotations

import json

from ios_wifi_loc.identifiers import IdentifierError, validate_udid
from ios_wifi_loc.runner import CommandResult, run
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


def _probe(name: str, argv: list[str], timeout: float, *, connection: str | None) -> dict:
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
    if connection is None or not result.ok:
        record["unparsed_excerpt"] = result.stdout[:500]
        return record
    try:
        udids = parse_simple_udids(result.stdout)
    except ValueError as exc:
        record["parse_error"] = str(exc)
        record["unparsed_excerpt"] = result.stdout[:500]
        return record
    record["devices"] = [
        {"udid": udid, "connection": connection, "source": name, "host": None, "name": None}
        for udid in udids
    ]
    return record


def discover(binary: str, *, timeout: float) -> dict:
    bounded = max(1.0, min(timeout, 30.0))
    browse_timeout = max(1, min(int(bounded), 30))
    probes = [
        _probe("usbmux_network", usbmux_list_argv(binary, kind="network"), bounded, connection="wifi"),
        _probe("usbmux_usb", usbmux_list_argv(binary, kind="usb"), bounded, connection="usb"),
        _probe("bonjour_mobdev2", bonjour_argv(binary), bounded, connection=None),
        _probe("remote_browse", remote_browse_argv(binary, browse_timeout), bounded + 2, connection=None),
    ]
    devices: list[dict] = []
    for probe in probes:
        devices.extend(probe["devices"])
    return {"probes": probes, "devices": devices}


def command_failed(result: CommandResult) -> str:
    if result.error == "binary_missing":
        return "找不到上游可执行文件"
    if result.error and result.error.startswith("os_error"):
        return "上游进程无法启动"
    if result.timed_out:
        return "上游命令超时"
    return f"上游命令退出码为 {result.returncode}"
