from __future__ import annotations

import os
import re
from pathlib import Path

from ios_wifi_loc.identifiers import IdentifierError, validate_udid

MAX_PLIST_SIZE = 256 * 1024
PLIST_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}\.plist$")
SYSTEM_CONFIGURATION = "SystemConfiguration.plist"


class PairingError(ValueError):
    pass


def lockdown_dir(state_dir: Path) -> Path:
    return state_dir / "lockdown"


def default_runtime_lockdown(root: Path | None = None) -> Path:
    return (root or Path("/")) / "var/lib/lockdown"


def validate_plist_filename(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise PairingError("文件名无效")
    if "/" in name or "\\" in name or name.startswith(".") and name not in {SYSTEM_CONFIGURATION}:
        if name != SYSTEM_CONFIGURATION:
            if ".." in name or "/" in name or "\\" in name:
                raise PairingError("文件名无效")
    base = Path(name).name
    if base != name or not PLIST_NAME.fullmatch(base):
        raise PairingError("只接受普通 .plist 文件名，不能包含路径")
    if ".." in base:
        raise PairingError("文件名无效")
    return base


def looks_like_plist(data: bytes) -> bool:
    if not isinstance(data, (bytes, bytearray)) or not data:
        return False
    if len(data) > MAX_PLIST_SIZE:
        return False
    raw = bytes(data)
    if raw.startswith(b"bplist"):
        return True
    text = raw.lstrip(b"\xef\xbb\xbf \t\r\n")
    return text.startswith(b"<?xml") or text.startswith(b"<plist")


def _udid_from_name(filename: str) -> str | None:
    stem = filename[:-6] if filename.lower().endswith(".plist") else filename
    try:
        return validate_udid(stem)
    except IdentifierError:
        return None


def list_pairing(state_dir: Path, *, runtime_dir: Path | None = None) -> dict:
    persist = lockdown_dir(state_dir)
    persist.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(persist, 0o700)
    files = []
    has_system = False
    for path in sorted(persist.glob("*.plist")):
        if not path.is_file():
            continue
        name = path.name
        try:
            name = validate_plist_filename(name)
        except PairingError:
            continue
        is_system = name == SYSTEM_CONFIGURATION
        if is_system:
            has_system = True
        files.append(
            {
                "filename": name,
                "udid": None if is_system else _udid_from_name(name),
                "system_configuration": is_system,
                "size": path.stat().st_size,
            }
        )
    runtime_count = 0
    if runtime_dir is not None and runtime_dir.is_dir():
        runtime_count = sum(1 for item in runtime_dir.glob("*.plist") if item.is_file())
    return {
        "count": len(files),
        "files": files,
        "has_system_configuration": has_system,
        "persist_dir": str(persist),
        "runtime_dir": None if runtime_dir is None else str(runtime_dir),
        "runtime_count": runtime_count,
    }


def _write_plist(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def import_plist(
    state_dir: Path,
    filename: str,
    data: bytes,
    *,
    runtime_dir: Path | None = None,
) -> dict:
    name = validate_plist_filename(filename)
    if not isinstance(data, (bytes, bytearray)):
        raise PairingError("文件内容无效")
    raw = bytes(data)
    if len(raw) == 0:
        raise PairingError("文件是空的")
    if len(raw) > MAX_PLIST_SIZE:
        raise PairingError("文件超过 256KB 上限")
    if not looks_like_plist(raw):
        raise PairingError("不是可识别的 plist 文件")
    persist = lockdown_dir(state_dir)
    _write_plist(persist / name, raw)
    runtime_written = False
    runtime_error = None
    if runtime_dir is not None:
        try:
            runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            _write_plist(runtime_dir / name, raw)
            runtime_written = True
        except OSError as exc:
            runtime_error = exc.__class__.__name__
    report = list_pairing(state_dir, runtime_dir=runtime_dir)
    report["imported"] = name
    report["runtime_written"] = runtime_written
    report["runtime_error"] = runtime_error
    return report


def delete_plist(state_dir: Path, filename: str, *, runtime_dir: Path | None = None) -> dict:
    name = validate_plist_filename(filename)
    persist = lockdown_dir(state_dir) / name
    if persist.exists():
        persist.unlink()
    if runtime_dir is not None:
        runtime = runtime_dir / name
        if runtime.exists() and runtime.is_file():
            try:
                runtime.unlink()
            except OSError:
                pass
    report = list_pairing(state_dir, runtime_dir=runtime_dir)
    report["deleted"] = name
    return report


def sync_lockdown(
    state_dir: Path,
    *,
    runtime_dir: Path,
    backup_runtime: bool = True,
) -> dict:
    persist = lockdown_dir(state_dir)
    persist.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(persist, 0o700)
    copied_in = 0
    copied_out = 0
    if backup_runtime and runtime_dir.is_dir():
        for path in runtime_dir.glob("*.plist"):
            if not path.is_file():
                continue
            try:
                name = validate_plist_filename(path.name)
            except PairingError:
                continue
            destination = persist / name
            if not destination.exists():
                _write_plist(destination, path.read_bytes())
                copied_in += 1
    try:
        runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        return {"copied_in": copied_in, "copied_out": 0, "runtime_ready": False}
    for path in persist.glob("*.plist"):
        if not path.is_file():
            continue
        try:
            name = validate_plist_filename(path.name)
        except PairingError:
            continue
        _write_plist(runtime_dir / name, path.read_bytes())
        copied_out += 1
    return {"copied_in": copied_in, "copied_out": copied_out, "runtime_ready": True}
