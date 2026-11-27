#!/usr/bin/env python3
"""Fail if the published tree contains pairing material or private keys."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "reports"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".crt", ".mobileprovision", ".plist"}
PEM_LINE = re.compile(r"(?m)^-----BEGIN [A-Z0-9 ]+-----\s*$")


def main() -> int:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith("remote_"):
            failures.append(f"forbidden file {path.relative_to(ROOT)}")
            continue
        if path.suffix.lower() not in {".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".json"} and path.name not in {"LICENSE", "pymobiledevice3"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if PEM_LINE.search(text):
            failures.append(f"{path.relative_to(ROOT)} contains a PEM header line")
    if failures:
        print("\n".join(failures))
        return 1
    print("secret scan: no pairing records, certificates, or PEM blocks in the tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
