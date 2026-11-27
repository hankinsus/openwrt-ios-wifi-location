from __future__ import annotations

import json
import os
from pathlib import Path


class StateError(ValueError):
    pass


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "state.json"

    def load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "selected": None, "session": None, "discovery": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError("状态文件损坏，已拒绝继续使用") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise StateError("状态文件版本无法识别")
        data.setdefault("selected", None)
        data.setdefault("session", None)
        data.setdefault("discovery", [])
        data.setdefault("favorites", [])
        data.setdefault("last_command", None)
        return data

    def save(self, data: dict) -> None:
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)
        payload = dict(data)
        payload["version"] = 1
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)
