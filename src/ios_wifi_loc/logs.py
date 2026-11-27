from __future__ import annotations

import os
from pathlib import Path

from ios_wifi_loc.redact import redact


def rotate_file(path: Path, *, max_bytes: int = 262144, backups: int = 2) -> None:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return
    oldest = path.with_name(path.name + f".{backups}")
    if oldest.exists():
        oldest.unlink()
    for index in range(backups - 1, 0, -1):
        source = path.with_name(path.name + f".{index}")
        target = path.with_name(path.name + f".{index + 1}")
        if source.exists():
            source.replace(target)
    path.replace(path.with_name(path.name + ".1"))


def append_log(path: Path, text: str, *, secret: str = "", max_bytes: int = 262144, backups: int = 2) -> None:
    cleaned = redact(text)
    if secret:
        cleaned = cleaned.replace(secret, "[已隐藏]")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    rotate_file(path, max_bytes=max_bytes, backups=backups)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(cleaned)
        if not cleaned.endswith("\n"):
            handle.write("\n")
    os.chmod(path, 0o600)
