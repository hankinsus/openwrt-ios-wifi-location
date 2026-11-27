from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ios_wifi_loc.redact import redact

MAX_CAPTURE = 256 * 1024
_STRIP_PREFIXES = ("PYMOBILEDEVICE3_",)
_STRIP_EXACT = {"USBMUXD_SOCKET_ADDRESS"}


class RunnerError(RuntimeError):
    pass


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out and self.returncode == 0


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if key not in _STRIP_EXACT and not key.startswith(_STRIP_PREFIXES)}
    env["NO_COLOR"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _cap(text: str) -> str:
    if len(text) > MAX_CAPTURE:
        text = text[:MAX_CAPTURE] + "\n[输出已截断]"
    return redact(text)


def _kill_group(pid: int) -> None:
    if pid <= 1:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            break
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def run(argv: list[str], *, timeout: float, env: dict[str, str] | None = None) -> CommandResult:
    if not argv or not isinstance(argv, list) or any(not isinstance(part, str) for part in argv):
        raise RunnerError("命令必须是字符串列表")
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=child_env(env),
        )
    except FileNotFoundError:
        return CommandResult(list(argv), None, "", "", False, 0.0, "binary_missing")
    except OSError as exc:
        return CommandResult(list(argv), None, "", "", False, 0.0, f"os_error:{exc.errno}")
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            stdout, stderr = b"", b""
        return CommandResult(
            list(argv),
            proc.returncode,
            _cap(stdout.decode("utf-8", "replace")),
            _cap(stderr.decode("utf-8", "replace")),
            True,
            time.monotonic() - started,
            "timeout",
        )
    return CommandResult(
        list(argv),
        proc.returncode,
        _cap(stdout.decode("utf-8", "replace")),
        _cap(stderr.decode("utf-8", "replace")),
        False,
        time.monotonic() - started,
        None,
    )


def spawn(argv: list[str], *, stdout_path: Path, stderr_path: Path, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    from ios_wifi_loc.logs import rotate_file

    stdout_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    rotate_file(stdout_path)
    rotate_file(stderr_path)
    out = open(stdout_path, "ab")
    err = open(stderr_path, "ab")
    os.chmod(stdout_path, 0o600)
    os.chmod(stderr_path, 0o600)
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
            env=child_env(env),
        )
    finally:
        out.close()
        err.close()
    return proc


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_args(pid: int) -> str:
    proc_path = Path(f"/proc/{pid}/cmdline")
    if proc_path.exists():
        raw = proc_path.read_bytes().replace(b"\x00", b" ")
        return raw.decode("utf-8", "replace")
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "args="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout or ""


def holder_matches(pid: int) -> bool:
    if not pid_alive(pid):
        return False
    text = process_args(pid)
    return "simulate-location" in text and "set" in text


def interrupt_holder(pid: int, *, wait_s: float) -> dict[str, object]:
    if pid <= 1:
        return {"signaled": False, "exited": False, "reason": "refused_pid"}
    if not pid_alive(pid):
        return {"signaled": False, "exited": True, "reason": "not_running"}
    if not holder_matches(pid):
        return {"signaled": False, "exited": False, "reason": "cmdline_mismatch"}
    try:
        os.killpg(pid, signal.SIGINT)
    except ProcessLookupError:
        return {"signaled": False, "exited": True, "reason": "not_running"}
    except PermissionError:
        return {"signaled": False, "exited": False, "reason": "permission"}
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return {"signaled": True, "exited": True, "reason": "exited"}
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return {"signaled": True, "exited": True, "reason": "exited"}
    exited = not pid_alive(pid)
    return {
        "signaled": True,
        "exited": exited,
        "reason": "killed" if exited else "unconfirmed",
    }
