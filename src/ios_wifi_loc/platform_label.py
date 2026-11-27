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
DEFAULT_OPENWRT_RELEASE = Path("/etc/openwrt_release")


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


def _label_from_release_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    fields = parse_os_release(text)
    ident = (fields.get("ID") or fields.get("DISTRIB_ID") or "").strip().lower()
    if ident in KNOWN_IDS:
        return KNOWN_IDS[ident]
    short = _name_short(fields.get("NAME") or fields.get("DISTRIB_ID") or fields.get("DISTRIB_DESCRIPTION") or "")
    return short


def detect_platform_label(
    os_release_path: str | Path | None = None,
    *,
    system: str | None = None,
    openwrt_release_path: str | Path | None = None,
) -> str:
    """Return a short host label such as OpenWrt / Ubuntu, or '' if unknown.

    `os_release_path=None` means `/etc/os-release` (DEFAULT_OS_RELEASE), looked up
    at call time so footer_brand() default args still read the real file.
    Pass an explicit path to inject a fixture; use a missing path to skip the file.
    If os-release is missing or empty, fall back to `/etc/openwrt_release`.
    `system` defaults to `sys.platform` and is used for macOS when no release file exists.
    """
    os_path = Path(os_release_path) if os_release_path is not None else DEFAULT_OS_RELEASE
    label = _label_from_release_file(os_path)
    if label:
        return label
    ow_path = Path(openwrt_release_path) if openwrt_release_path is not None else DEFAULT_OPENWRT_RELEASE
    label = _label_from_release_file(ow_path)
    if label:
        return label
    host = (system if system is not None else sys.platform).strip().lower()
    if host in {"darwin", "macos", "osx"}:
        return "macOS"
    return ""
