from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path


class StateError(ValueError):
    pass


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "state.json"
        self.lock_path = directory / "state.lock"

    def _ensure_dir(self) -> None:
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(self.directory, 0o700)

    def _lock_handle(self):
        self._ensure_dir()
        handle = open(self.lock_path, "a+")
        try:
            os.chmod(self.lock_path, 0o600)
        except OSError:
            pass
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _empty(self) -> dict:
        return {"version": 1, "selected": None, "session": None, "sessions": {}, "discovery": []}

    def _load_unlocked(self) -> dict:
        if not self.path.exists():
            return self._empty()
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
        data.setdefault("sessions", {})
        return data

    def _save_unlocked(self, data: dict) -> None:
        self._ensure_dir()
        payload = dict(data)
        payload["version"] = 1
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def load(self) -> dict:
        handle = self._lock_handle()
        try:
            return self._load_unlocked()
        finally:
            handle.close()

    def save(self, data: dict) -> None:
        handle = self._lock_handle()
        try:
            self._save_unlocked(data)
        finally:
            handle.close()

    @contextmanager
    def transaction(self):
        handle = self._lock_handle()
        try:
            data = self._load_unlocked()
            yield data
            self._save_unlocked(data)
        finally:
            handle.close()
