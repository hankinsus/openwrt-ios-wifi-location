#!/usr/bin/env python3
"""Run the installed pymobiledevice3 CLI and record help text.

A missing marker fails the process. This does not talk to an iPhone and does
not treat a successful help page as device support.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ios_wifi_loc.redact import redact  # noqa: E402
from ios_wifi_loc.runner import run  # noqa: E402

REQUIRED = [
    (["developer", "dvt", "simulate-location", "set", "--help"], ["latitude", "longitude"]),
    (["developer", "simulate-location", "set", "--help"], ["latitude", "longitude"]),
    (["developer", "dvt", "simulate-location", "clear", "--help"], []),
    (["usbmux", "list", "--help"], ["--network", "--simple"]),
    (["remote", "browse", "--help"], []),
    (["lockdown", "info", "--help"], []),
]
RECORDED = [
    ["version"],
    ["--version"],
    ["bonjour", "mobdev2", "--help"],
    ["remote", "pair-host", "--help"],
    ["lockdown", "wifi-connections", "--help"],
    ["lockdown", "remotepairing", "--help"],
]


def _safe_name(argv: list[str]) -> str:
    return " ".join(argv).replace("/", "_")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=shutil.which("pymobiledevice3") or "pymobiledevice3")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    binary = args.binary
    rows = []
    failed = False
    for argv, markers in REQUIRED:
        result = run([binary, *argv], timeout=60)
        text = redact(result.stdout + "\n" + result.stderr)
        (out / (_safe_name(argv) + ".txt")).write_text(text, encoding="utf-8")
        missing = [marker for marker in markers if marker not in text]
        ok = result.ok and not missing
        failed = failed or not ok
        rows.append({"argv": argv, "returncode": result.returncode, "error": result.error, "missing": missing, "required": True, "ok": ok})
    for argv in RECORDED:
        result = run([binary, *argv], timeout=60)
        text = redact(result.stdout + "\n" + result.stderr)
        (out / (_safe_name(argv) + ".txt")).write_text(text, encoding="utf-8")
        rows.append({"argv": argv, "returncode": result.returncode, "error": result.error, "required": False, "ok": result.ok})
    version_ok = any(row["argv"] in (["version"], ["--version"]) and row["ok"] and any(ch.isdigit() for ch in Path(out / (_safe_name(row["argv"]) + ".txt")).read_text(encoding="utf-8")) for row in rows)
    summary = {
        "binary": binary,
        "required_ok": not failed,
        "version_help_ok": version_ok,
        "physical_iphone": False,
        "rows": rows,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failed or not version_ok:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"required_ok": True, "version_help_ok": True, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
