from __future__ import annotations

import re

_UDID = re.compile(
    r"^(?:[A-Fa-f0-9]{24}|[A-Fa-f0-9]{40}|"
    r"[A-Fa-f0-9]{8}-[A-Fa-f0-9]{16}|"
    r"[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12})$"
)
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_USBMUX_PATH = re.compile(r"^/[\w./@+-]{1,200}$")
_USBMUX_TCP = re.compile(r"^[A-Za-z0-9.-]{1,253}:(\d{1,5})$")
_NAME = re.compile(r"^[\w .()+\-]{1,64}$", re.UNICODE)


class IdentifierError(ValueError):
    pass


def validate_udid(value: str) -> str:
    if not isinstance(value, str) or not _UDID.fullmatch(value):
        raise IdentifierError("UDID 格式不被接受。只允许 24/40 位十六进制、旧式 8-16 或 UUID。")
    return value


def _ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
            return False
        number = int(part)
        if number > 255:
            return False
    return True


def validate_host(value: str) -> str:
    if not isinstance(value, str) or any(ch in value for ch in " \t\r\n;|&$`<>\\"):
        raise IdentifierError("主机名含有不允许的字符")
    if value.count(".") == 3 and all(part.isdigit() for part in value.split(".")):
        if not _ipv4(value):
            raise IdentifierError("IPv4 地址的每一段必须在 0 到 255")
        return value
    if _HOST.fullmatch(value):
        return value
    raise IdentifierError("主机必须是 IPv4 或普通域名")


def validate_usbmux_address(value: str) -> str:
    if not isinstance(value, str) or value.startswith("-"):
        raise IdentifierError("usbmux 地址无效")
    tcp = _USBMUX_TCP.fullmatch(value)
    if tcp:
        port = int(tcp.group(1))
        if 1 <= port <= 65535:
            return value
    if _USBMUX_PATH.fullmatch(value):
        return value
    raise IdentifierError("usbmux 地址必须是绝对套接字路径或 host:port")


def validate_name(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _NAME.fullmatch(value):
        raise IdentifierError("设备显示名含有不允许的字符")
    return value
