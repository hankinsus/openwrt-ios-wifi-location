from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from ios_wifi_loc.identifiers import IdentifierError, validate_udid
from ios_wifi_loc.runner import child_env, pid_alive
from ios_wifi_loc.session import (
    _put_session,
    _session_for,
    _session_logs,
)
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.tunneld import tunnel_ready_for
from ios_wifi_loc.upstream import PlanError, Target, location_argv

ERROR_MARKERS = (
    "DTX reader exiting",
    "Network unreachable",
    "Errno 101",
    "[Errno 101]",
)


def _safe_udid(udid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in udid)


def stop_path(store: StateStore, udid: str) -> Path:
    return store.directory / f"hold.{_safe_udid(udid)}.stop"


def request_stop(store: StateStore, udid: str) -> None:
    path = stop_path(store, udid)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_text("stop\n", encoding="utf-8")
    os.chmod(path, 0o600)


def clear_stop(store: StateStore, udid: str) -> None:
    path = stop_path(store, udid)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def backoff_series() -> list[float]:
    raw = os.environ.get("IOS_WIFI_LOC_WATCHDOG_BACKOFF", "3,5,10")
    delays: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            delays.append(max(0.01, min(10.0, float(part))) )
        except ValueError:
            continue
    return delays or [3.0, 5.0, 10.0]


def log_contains_error(path: Path, offset: int) -> tuple[bool, str, int]:
    if not path.exists():
        return False, "", offset
    data = path.read_bytes()
    new = data[offset:]
    offset = len(data)
    text = new.decode("utf-8", "replace")
    for marker in ERROR_MARKERS:
        if marker in text:
            excerpt = text.strip().replace("\n", " ")
            return True, excerpt[-400:], offset
    return False, "", offset


def _sleep(seconds: float, stopped) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if stopped():
            return
        time.sleep(min(0.05, deadline - time.monotonic()))


def spawn_child(argv: list[str], stdout_path: Path, stderr_path: Path, *, rotate: bool) -> subprocess.Popen[bytes]:
    from ios_wifi_loc.logs import rotate_file

    stdout_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if rotate:
        rotate_file(stdout_path)
        rotate_file(stderr_path)
    out = open(stdout_path, "ab")
    err = open(stderr_path, "ab")
    os.chmod(stdout_path, 0o600)
    os.chmod(stderr_path, 0o600)
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=False,
            env=child_env(),
        )
    finally:
        out.close()
        err.close()


def _kill_child(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    pid = proc.pid
    if pid <= 1:
        return
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        if proc.poll() is not None or not pid_alive(pid):
            return
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + (0.4 if sig != signal.SIGKILL else 0.2)
        while time.monotonic() < deadline:
            if proc.poll() is not None or not pid_alive(pid):
                return
            time.sleep(0.02)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _update_session(store: StateStore, udid: str, **fields: object) -> dict:
    with store.transaction() as data:
        session = dict(_session_for(data, udid) or {})
        session.update(fields)
        session["udid"] = udid
        session["watchdog_pid"] = os.getpid()
        session["pid"] = os.getpid()
        session["watchdog_active"] = True
        _put_session(data, udid, session)
        return session


def hold_command_argv(
    python: str,
    store: StateStore,
    binary: str,
    target: Target,
    latitude: str,
    longitude: str,
    profile: str,
    grace: float,
    *,
    use_tunnel: bool,
) -> list[str]:
    parts = [
        python,
        "-m",
        "ios_wifi_loc",
        "--state-dir",
        str(store.directory),
        "--binary",
        binary,
        "_hold",
        "--udid",
        target.udid,
        "--transport",
        target.transport,
        "--profile",
        profile,
        "--latitude",
        latitude,
        "--longitude",
        longitude,
        "--startup-grace",
        str(grace),
    ]
    if target.host:
        parts.extend(["--host", target.host])
    if target.usbmux_address:
        parts.extend(["--usbmux-address", target.usbmux_address])
    if use_tunnel:
        parts.append("--use-tunnel")
    return parts


def run_hold(store: StateStore, args: object) -> int:
    try:
        udid = validate_udid(getattr(args, "udid"))
        target = Target(
            udid=udid,
            transport=getattr(args, "transport"),
            host=getattr(args, "host", None),
            usbmux_address=getattr(args, "usbmux_address", None),
        )
        lat = str(getattr(args, "latitude"))
        lon = str(getattr(args, "longitude"))
        profile = str(getattr(args, "profile") or "ios17")
        grace = float(getattr(args, "startup_grace") or 5)
        use_tunnel = bool(getattr(args, "use_tunnel", False))
        binary = str(getattr(args, "binary"))
        argv = location_argv(binary, target, "set", profile, lat, lon, use_tunnel=use_tunnel)
    except (PlanError, IdentifierError, ValueError, TypeError):
        return 2

    stop = {"flag": False}

    def _handle(_signum: int, _frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    def stopped() -> bool:
        if stop["flag"]:
            return True
        return stop_path(store, udid).exists()

    clear_stop(store, udid)
    log_out, log_err = _session_logs(store, udid)
    existing = _session_for(store.load(), udid) or {}
    reconnect_count = int(existing.get("reconnect_count") or 0)
    last_error = existing.get("last_error")
    _update_session(
        store,
        udid,
        profile=profile,
        latitude=lat,
        longitude=lon,
        argv=argv[1:],
        started_at=existing.get("started_at") or _now(),
        holding=False,
        child_pid=None,
        reconnect_count=reconnect_count,
        last_error=last_error,
        last_reconnect_at=existing.get("last_reconnect_at"),
        waiting_reconnect=False,
    )

    child: subprocess.Popen[bytes] | None = None
    attempt = 0
    try:
        while not stopped():
            if attempt > 0:
                _update_session(
                    store,
                    udid,
                    holding=False,
                    child_pid=None,
                    waiting_reconnect=True,
                    watchdog_active=True,
                    reconnect_count=reconnect_count,
                    last_error=last_error,
                    last_reconnect_at=_now(),
                )
                delays = backoff_series()
                delay = delays[min(attempt - 1, len(delays) - 1)]
                deadline = time.monotonic() + delay
                while time.monotonic() < deadline and not stopped():
                    if use_tunnel and tunnel_ready_for(udid):
                        break
                    time.sleep(0.05)
                if stopped():
                    break
            child = spawn_child(argv, log_out, log_err, rotate=(attempt == 0))
            offset = log_err.stat().st_size if log_err.exists() else 0
            _update_session(
                store,
                udid,
                holding=True,
                child_pid=child.pid,
                waiting_reconnect=False,
                watchdog_active=True,
                reconnect_count=reconnect_count,
                last_error=last_error,
            )
            if attempt == 0:
                deadline = time.monotonic() + max(0.05, grace)
                while time.monotonic() < deadline and child.poll() is None and not stopped():
                    time.sleep(0.05)
                if stopped():
                    break
                if child.poll() is not None:
                    tail = ""
                    if log_err.exists():
                        tail = log_err.read_bytes()[-500:].decode("utf-8", "replace")
                    _update_session(
                        store,
                        udid,
                        holding=False,
                        child_pid=None,
                        watchdog_active=False,
                        last_error=tail.strip() or f"exit {child.returncode}",
                    )
                    return 1 if child.returncode else 4
            while not stopped() and child.poll() is None:
                hit, excerpt, offset = log_contains_error(log_err, offset)
                if hit:
                    last_error = excerpt or "Network unreachable"
                    _kill_child(child)
                    break
                time.sleep(0.05)
            if stopped():
                break
            code = child.returncode if child is not None else None
            if last_error is None or child is not None and child.poll() is not None:
                tail = ""
                if log_err.exists():
                    tail = log_err.read_bytes()[-500:].decode("utf-8", "replace")
                if any(marker in tail for marker in ERROR_MARKERS):
                    last_error = next((marker for marker in ERROR_MARKERS if marker in tail), tail[-200:])
                elif tail.strip():
                    last_error = tail.strip()[-200:]
                else:
                    last_error = f"upstream exited ({code})"
            reconnect_count += 1
            attempt += 1
            child = None
        return 0
    finally:
        _kill_child(child)
        try:
            if stop_path(store, udid).exists():
                with store.transaction() as data:
                    session = _session_for(data, udid)
                    if session and session.get("watchdog_pid") == os.getpid():
                        _put_session(data, udid, None)
            else:
                data = store.load()
                session = _session_for(data, udid)
                if session and session.get("watchdog_pid") == os.getpid():
                    _update_session(
                        store,
                        udid,
                        holding=False,
                        child_pid=None,
                        watchdog_active=False,
                        waiting_reconnect=False,
                        last_error=last_error,
                        reconnect_count=reconnect_count,
                    )
        except Exception:
            pass
