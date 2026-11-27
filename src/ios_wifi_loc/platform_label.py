from __future__ import annotations

import sys
from pathlib import Path

KNOWN_IDS = {
    "openwrt": "OpenWrt",
    "ubuntu": "Ubuntu",
    "debian": "Debian",
    "alpine": "Alpine",
    "macos": "macOS",
    "darwin": "macOS",
}

DEFAULT_OS_RELEASE = Path("/etc/os-release")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_os_release(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            data[key] = _unquote(value)
    return data


def _name_short(name: str) -> str:
    token = (name or "").strip().split(None, 1)[0] if (name or "").strip() else ""
    return token.strip(".,;:()[]{}")


def detect_platform_label(
    os_release_path: str | Path | None = DEFAULT_OS_RELEASE,
    *,
    system: str | None = None,
) -> str:
    """Return a short host label such as OpenWrt / Ubuntu, or '' if unknown.

    `os_release_path` defaults to `/etc/os-release` and can be injected in tests.
    `system` defaults to `sys.platform` and is used for macOS when no os-release file exists.
    """
    path = Path(os_release_path) if os_release_path is not None else None
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        else:
            fields = parse_os_release(text)
            ident = (fields.get("ID") or "").strip().lower()
            if ident in KNOWN_IDS:
                return KNOWN_IDS[ident]
            short = _name_short(fields.get("NAME") or "")
            if short:
                return short
    host = (system if system is not None else sys.platform).strip().lower()
    if host in {"darwin", "macos", "osx"}:
        return "macOS"
    return ""
