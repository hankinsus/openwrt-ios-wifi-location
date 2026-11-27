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


def process_state(pid: int) -> str | None:
    """Return the /proc status letter (R/S/Z/...) or None if the pid is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    close = stat.rfind(")")
    if close == -1 or close + 2 >= len(stat):
        return None
    return stat[close + 2]


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # May still inspect /proc; a zombie is not a live holder.
        pass
    state = process_state(pid)
    if state is None:
        return Path("/proc").is_dir() is False
    return state not in {"Z", "X"}


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
    tokens = text.split()
    if "_hold" in tokens or "_simulate" in tokens:
        return True
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


def list_process_table() -> list[tuple[int, str]]:
    """Return (pid, command line) pairs for the current process table."""
    rows: list[tuple[int, str]] = []
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
            except ValueError:
                continue
            if process_state(pid) in {"Z", "X"}:
                continue
            cmdline = process_args(pid)
            if cmdline.strip():
                rows.append((pid, cmdline))
        return rows
    result = subprocess.run(
        ["ps", "-ax", "-o", "pid=,args="],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        rows.append((int(parts[0]), parts[1] if len(parts) > 1 else ""))
    return rows


def is_holder_command(text: str) -> bool:
    tokens = (text or "").split()
    if "_hold" in tokens or "_simulate" in tokens:
        return True
    return "simulate-location" in text and "set" in tokens


def is_tunneld_command(text: str) -> bool:
    tokens = (text or "").split()
    return "tunneld" in tokens and "remote" in tokens


def pids_matching(*, udid: str | None = None, state_dir: Path | str | None = None, holders: bool = True, tunneld: bool = False) -> list[int]:
    """Find leftover location / tunneld processes, optionally scoped to a UDID or state dir."""
    me = os.getpid()
    needle_udid = str(udid) if udid else ""
    needle_state = str(state_dir) if state_dir is not None else ""
    found: list[int] = []
    for pid, text in list_process_table():
        if pid in {me, 0, 1} or pid in found:
            continue
        if needle_udid and needle_udid not in text:
            if not needle_state or needle_state not in text:
                continue
        if needle_state and needle_state not in text and (not needle_udid or needle_udid not in text):
            continue
        if holders and is_holder_command(text):
            if needle_udid and needle_udid not in text:
                continue
            found.append(pid)
            continue
        if tunneld and is_tunneld_command(text):
            found.append(pid)
    return found


def terminate_pids(pids: list[int], *, timeout: float = 5) -> dict:
    """SIGINT/SIGTERM the process group, then SIGKILL anything still alive."""
    unique: list[int] = []
    me = os.getpid()
    for pid in pids:
        if not isinstance(pid, int) or pid <= 1 or pid == me or pid in unique:
            continue
        unique.append(pid)
    signaled = 0
    for pid in unique:
        if not pid_alive(pid):
            continue
        signaled += 1
        for sig, use_group in ((signal.SIGINT, True), (signal.SIGTERM, True), (signal.SIGTERM, False)):
            if not pid_alive(pid):
                break
            try:
                os.killpg(pid, sig) if use_group else os.kill(pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                if use_group:
                    try:
                        os.kill(pid, sig)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
        deadline = time.monotonic() + max(0.05, timeout)
        while time.monotonic() < deadline and pid_alive(pid):
            time.sleep(0.05)
        if pid_alive(pid):
            for use_group in (True, False):
                try:
                    os.killpg(pid, signal.SIGKILL) if use_group else os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass
    return {
        "pids": unique,
        "signaled": signaled,
        "remaining": [pid for pid in unique if pid_alive(pid)],
    }

