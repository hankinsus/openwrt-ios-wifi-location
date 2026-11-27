from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_TOKEN = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_MAX_LEN = 32


class CoordError(ValueError):
    pass


def parse_coord(text: str, kind: str) -> Decimal:
    if kind not in {"latitude", "longitude"}:
        raise CoordError("坐标类型无效")
    if not isinstance(text, str):
        raise CoordError(f"{kind} 必须是十进制字符串")
    raw = text.strip()
    if not raw or len(raw) > _MAX_LEN or not _TOKEN.fullmatch(raw):
        raise CoordError(f"{kind} 只能是有限十进制数，不接受科学计数法、空值或其它字符")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise CoordError(f"{kind} 无法解析") from exc
    if not value.is_finite():
        raise CoordError(f"{kind} 不是有限数")
    limit = Decimal("90") if kind == "latitude" else Decimal("180")
    if value < -limit or value > limit:
        raise CoordError(f"{kind} 超出合法范围")
    return value


def canonical(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-", "-0"}:
        return "0"
    return rendered


def parse_pair(latitude: str, longitude: str) -> tuple[str, str]:
    lat = canonical(parse_coord(latitude, "latitude"))
    lon = canonical(parse_coord(longitude, "longitude"))
    return lat, lon
