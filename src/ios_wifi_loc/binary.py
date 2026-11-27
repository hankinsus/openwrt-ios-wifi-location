from __future__ import annotations

import shutil
import sys
from pathlib import Path

from ios_wifi_loc.upstream import executable

DEFAULT_BINARY_NAME = "pymobiledevice3"


def _sibling_candidates(python_executable: str) -> list[Path]:
    raw = Path(python_executable)
    candidates = []
    try:
        candidates.append(raw.resolve().parent / DEFAULT_BINARY_NAME)
    except OSError:
        pass
    candidates.append(raw.parent / DEFAULT_BINARY_NAME)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _existing_sibling(python_executable: str) -> Path | None:
    found_file = None
    for path in _sibling_candidates(python_executable):
        if path.is_file() and _is_executable(path):
            return path
        if path.is_file() and found_file is None:
            found_file = path
    return found_file


def _is_executable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False


def in_virtualenv(python_executable: str | None = None) -> bool:
    exe = python_executable or sys.executable
    if python_executable in {None, sys.executable}:
        if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
            return True
        if hasattr(sys, "real_prefix"):
            return True
    parent = Path(exe).parent
    return parent.name == "bin" and ((parent / "python3").exists() or (parent / "python").exists())


def resolve_binary(binary: str = DEFAULT_BINARY_NAME, *, python_executable: str | None = None) -> str:
    """Resolve the pymobiledevice3 executable.

    An explicit non-default path or name is returned as-is after validation.
    When the default name is used, prefer a venv sibling of the running
    interpreter (OpenWrt procd often has no PATH entry), then shutil.which.
    """
    checked = executable(binary)
    if checked != DEFAULT_BINARY_NAME:
        return checked
    python = python_executable or sys.executable
    sibling = _existing_sibling(python)
    found = shutil.which(DEFAULT_BINARY_NAME)
    if sibling is not None and (python_executable is not None or in_virtualenv(python) or not found):
        return str(sibling)
    if found:
        return found
    if sibling is not None:
        return str(sibling)
    return DEFAULT_BINARY_NAME


def infer_binary_from_python(python_executable: str | None) -> str | None:
    if not python_executable:
        return None
    path = Path(python_executable)
    if path.parent.name != "bin":
        return None
    return str(path.parent / DEFAULT_BINARY_NAME)
