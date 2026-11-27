from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ios_wifi_loc.coords import parse_pair
from ios_wifi_loc.identifiers import validate_host, validate_udid, validate_usbmux_address

TRANSPORTS = ("usbmux", "mobdev2", "remotepairing")
PROFILES = ("pre17", "ios17")
_VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_HELP_TOKENS = {
    "developer",
    "dvt",
    "simulate-location",
    "set",
    "clear",
    "remote",
    "browse",
    "pair-host",
    "usbmux",
    "list",
    "bonjour",
    "mobdev2",
    "lockdown",
    "info",
    "wifi-connections",
    "remotepairing",
    "version",
}
BANNED_ARGV_TOKENS = {
    "unpair",
    "tunneld",
    "start-tunnel",
    "forward",
    "recovery",
    "pair",
    "delete-pair",
    "save-pair-record",
    "pair-supervised",
    "pair-wireless",
}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    udid: str
    transport: str
    host: str | None = None
    usbmux_address: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "udid", validate_udid(self.udid))
        if self.transport not in TRANSPORTS:
            raise PlanError("传输方式必须是 usbmux、mobdev2 或 remotepairing")
        host = self.host
        if host is not None:
            host = validate_host(host)
            object.__setattr__(self, "host", host)
        address = self.usbmux_address
        if address is not None:
            address = validate_usbmux_address(address)
            object.__setattr__(self, "usbmux_address", address)
        if self.transport != "mobdev2" and host is not None:
            raise PlanError("只有 mobdev2 可以带主机地址")
        if self.transport != "usbmux" and address is not None:
            raise PlanError("只有 usbmux 可以带套接字地址")


def executable(binary: str) -> str:
    if not isinstance(binary, str) or not binary or binary.startswith("-"):
        raise PlanError("上游可执行文件无效")
    if any(ch in binary for ch in "\x00\n\r;&|$`<>"):
        raise PlanError("上游可执行文件含有不允许的字符")
    return binary


def connection_flags(target: Target) -> list[str]:
    # --usbmux takes a socket address. A bare --usbmux would swallow the next
    # argument, so the default usbmux path passes only --udid.
    # --mobdev2-host and --mobdev2 are mutually exclusive in pymobiledevice3 11.63.1.
    flags = ["--udid", target.udid]
    if target.transport == "usbmux":
        if target.usbmux_address:
            flags.extend(["--usbmux", target.usbmux_address])
    elif target.transport == "mobdev2":
        if target.host:
            flags.extend(["--mobdev2-host", target.host])
        else:
            flags.append("--mobdev2")
    elif target.transport == "remotepairing":
        flags.append("--remotepairing")
    _reject_banned(flags)
    return flags


def _reject_banned(argv: list[str]) -> None:
    found = BANNED_ARGV_TOKENS.intersection(argv)
    if found:
        raise PlanError("拒绝构造被禁止的上游命令")


def location_argv(
    binary: str,
    target: Target,
    action: str,
    profile: str,
    latitude: str | None = None,
    longitude: str | None = None,
) -> list[str]:
    if action not in {"set", "clear"}:
        raise PlanError("定位动作无效")
    if profile not in PROFILES:
        raise PlanError("定位命令族无效")
    argv = [executable(binary), "developer"]
    if profile == "ios17":
        argv.append("dvt")
    argv.extend(["simulate-location", action, *connection_flags(target)])
    if action == "set":
        if latitude is None or longitude is None:
            raise PlanError("缺少坐标")
        lat, lon = parse_pair(latitude, longitude)
        argv.extend(["--", lat, lon])
    _reject_banned(argv[1:])
    return argv


def lockdown_info_argv(binary: str, target: Target) -> list[str]:
    argv = [executable(binary), "lockdown", "info", *connection_flags(target)]
    _reject_banned(argv[1:])
    return argv


def usbmux_list_argv(binary: str, *, kind: str) -> list[str]:
    if kind not in {"network", "usb"}:
        raise PlanError("usbmux 列表类型无效")
    flag = "--network" if kind == "network" else "--usb"
    argv = [executable(binary), "usbmux", "list", flag, "--simple"]
    _reject_banned(argv[1:])
    return argv


def bonjour_argv(binary: str) -> list[str]:
    argv = [executable(binary), "bonjour", "mobdev2"]
    _reject_banned(argv[1:])
    return argv


def remote_browse_argv(binary: str, timeout_seconds: int) -> list[str]:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise PlanError("browse 超时无效")
    if timeout_seconds < 1 or timeout_seconds > 30:
        raise PlanError("browse 超时必须在 1 到 30 秒")
    argv = [executable(binary), "remote", "browse", "--timeout", str(timeout_seconds)]
    _reject_banned(argv[1:])
    return argv


def version_argv(binary: str) -> list[str]:
    return [executable(binary), "version"]


def help_argv(binary: str, parts: list[str]) -> list[str]:
    if not parts or any(part not in _HELP_TOKENS for part in parts):
        raise PlanError("帮助探测命令不在允许列表")
    argv = [executable(binary), *parts, "--help"]
    return argv


def classify_product_version(version: str) -> str:
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise PlanError("ProductVersion 无法识别")
    major_s, minor_s, *_rest = version.split(".")
    major = int(major_s)
    minor = int(minor_s)
    if major < 17:
        return "pre17"
    if major == 17 and minor < 4:
        return "ios17_needs_tunneld"
    return "ios17"


def extract_product_version(text: str) -> str | None:
    candidate = text.strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("ProductVersion"), str):
        value = data["ProductVersion"]
        if _VERSION.fullmatch(value):
            return value
    match = re.search(r'"ProductVersion"\s*:\s*"(\d+\.\d+(?:\.\d+)?)"', text)
    if match:
        return match.group(1)
    return None
