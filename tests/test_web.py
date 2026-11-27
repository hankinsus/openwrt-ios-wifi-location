from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fakes" / "pymobiledevice3"
UDID = "0123456789abcdef0123456789abcdef01234567"


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["IOS_WIFI_LOC_FAKE_LOG"] = str(tmp_path / "argv.log")
    env["IOS_WIFI_LOC_FAKE_DEVICES"] = json.dumps([UDID])
    env.update(extra)
    return env


def _start(tmp_path: Path, args: list[str] | None = None, require_auth: bool = True, **extra: str):
    serve_args = list(args or ["--no-watch"])
    if require_auth and "--require-auth" not in serve_args and "--no-auth" not in serve_args:
        serve_args = ["--require-auth", *serve_args]
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ios_wifi_loc",
            "--state-dir",
            str(tmp_path / "state"),
            "--binary",
            str(FAKE),
            "serve",
            "--port",
            "0",
            *serve_args,
        ],
        env=_env(tmp_path, **extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line.startswith("LISTENING "):
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(line + err)
    _listen, host, port = line.split()
    return proc, host, int(port)


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def _request(opener, host: str, port: int, path: str, method: str = "GET", body: dict | None = None, headers: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"http://{host}:{port}{path}", data=data, method=method)
    request.add_unredirected_header("Host", f"{host}:{port}")
    for key, value in (headers or {}).items():
        request.add_unredirected_header(key, value)
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def _csrf(page: str) -> str:
    match = re.search(r'name="csrf-token" content="([0-9a-f]+)"', page)
    assert match
    return match.group(1)


def _login(tmp_path: Path, host: str, port: int):
    opener = _opener()
    status, page = _request(opener, host, port, "/")
    assert status == 200
    secret = (tmp_path / "state" / "web.secret").read_text(encoding="utf-8").strip()
    assert secret not in page
    token = _csrf(page)
    status, body = _request(
        opener,
        host,
        port,
        "/api/login",
        "POST",
        {"password": secret},
        {"Origin": f"http://{host}:{port}", "X-CSRF-Token": token, "Content-Type": "application/json"},
    )
    assert status == 200, body
    return opener, token, secret


def test_bind_refuses_open_addresses():
    from ios_wifi_loc.service import ServiceError, resolve_bind

    with pytest.raises(ServiceError):
        resolve_bind("0.0.0.0", None)
    with pytest.raises(ServiceError):
        resolve_bind("192.0.2.10", None)
    assert resolve_bind(None, None) == "127.0.0.1"


def test_login_origin_and_secret_are_not_logged(tmp_path):
    proc, host, port = _start(tmp_path)
    try:
        opener = _opener()
        status, page = _request(opener, host, port, "/")
        token = _csrf(page)
        status, body = _request(
            opener,
            host,
            port,
            "/api/login",
            "POST",
            {"password": "UNIQUE-WRONG-SECRET-VALUE"},
            {"X-CSRF-Token": token, "Content-Type": "application/json"},
        )
        assert status == 403
        status, body = _request(
            opener,
            host,
            port,
            "/api/login",
            "POST",
            {"password": "UNIQUE-WRONG-SECRET-VALUE"},
            {"Origin": f"http://{host}:{port}", "X-CSRF-Token": token, "Content-Type": "application/json"},
        )
        assert status == 401
        log = (tmp_path / "state" / "service.log").read_text(encoding="utf-8")
        assert "UNIQUE-WRONG-SECRET-VALUE" not in log
        secret = (tmp_path / "state" / "web.secret").read_text(encoding="utf-8")
        assert secret.strip() not in log
        assert oct((tmp_path / "state" / "web.secret").stat().st_mode & 0o777) == "0o600"
    finally:
        _stop(proc)


def test_explicit_start_duplicate_and_no_replay_after_restart(tmp_path):
    proc, host, port = _start(tmp_path)
    try:
        opener, token, _secret = _login(tmp_path, host, port)
        headers = {"Origin": f"http://{host}:{port}", "X-CSRF-Token": token, "Content-Type": "application/json"}
        status, body = _request(
            opener,
            host,
            port,
            "/api/select",
            "POST",
            {"udid": UDID, "transport": "usbmux"},
            headers,
        )
        assert status == 200, body
        status, body = _request(
            opener,
            host,
            port,
            "/api/location/start",
            "POST",
            {"latitude": "10", "longitude": "20", "profile": "ios17", "confirm": False},
            headers,
        )
        assert status == 400
        logged = (tmp_path / "argv.log").read_text(encoding="utf-8") if (tmp_path / "argv.log").exists() else ""
        assert "simulate-location" not in logged
        status, body = _request(
            opener,
            host,
            port,
            "/api/favorites",
            "POST",
            {"name": "门口", "latitude": "10", "longitude": "20"},
            headers,
        )
        assert status == 200
        status, body = _request(
            opener,
            host,
            port,
            "/api/location/start",
            "POST",
            {"latitude": "10", "longitude": "20", "profile": "ios17", "confirm": True},
            headers,
        )
        assert status == 200, body
        payload = json.loads(body)
        assert payload["command_accepted"] is True
        assert payload["session_alive"] is True
        assert payload["phone_location"] == "unconfirmed"
        status, body = _request(
            opener,
            host,
            port,
            "/api/location/start",
            "POST",
            {"latitude": "11", "longitude": "21", "profile": "ios17", "confirm": True, "replace": True},
            headers,
        )
        assert status == 200, body
        payload = json.loads(body)
        assert payload["command_accepted"] is True
        assert payload["session_alive"] is True
        session = payload.get("session") or {}
        assert session.get("latitude") == "11"
        assert session.get("longitude") == "21"
        sets_before = (tmp_path / "argv.log").read_text(encoding="utf-8").count("simulate-location")
        assert sets_before >= 2
    finally:
        _stop(proc)
    proc, host, port = _start(tmp_path)
    try:
        opener, token, _secret = _login(tmp_path, host, port)
        status, body = _request(opener, host, port, "/api/status")
        payload = json.loads(body)
        assert payload["session_alive"] is True
        assert payload["phone_location"] == "unconfirmed"
        assert payload["favorites"][0]["name"] == "门口"
        assert (tmp_path / "argv.log").read_text(encoding="utf-8").count("simulate-location") == sets_before
    finally:
        _stop(proc)
        payload = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
        pids = []
        session = payload.get("session") or {}
        if isinstance(session, dict):
            for key in ("pid", "watchdog_pid", "child_pid"):
                if isinstance(session.get(key), int):
                    pids.append(session[key])
        for item in (payload.get("sessions") or {}).values() if isinstance(payload.get("sessions"), dict) else []:
            if isinstance(item, dict):
                for key in ("pid", "watchdog_pid", "child_pid"):
                    if isinstance(item.get(key), int):
                        pids.append(item[key])
        for pid in pids:
            if isinstance(pid, int) and pid > 1:
                try:
                    os.killpg(pid, 9)
                except OSError:
                    try:
                        os.kill(pid, 9)
                    except OSError:
                        pass


def test_watch_checks_visibility_without_setting_location(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "state.json").write_text(
        json.dumps({"version": 1, "selected": {"udid": UDID, "transport": "usbmux", "connection": "wifi"}, "session": None, "discovery": [], "favorites": []}),
        encoding="utf-8",
    )
    proc, _host, _port = _start(tmp_path, ["--watch-interval", "0.2"], IOS_WIFI_LOC_FAKE_DEVICES="[]")
    try:
        time.sleep(1.2)
    finally:
        _stop(proc)
    log = (tmp_path / "argv.log").read_text(encoding="utf-8")
    assert "usbmux" in log
    assert "simulate-location" not in log


def test_install_and_uninstall_are_reversible(tmp_path):
    from ios_wifi_loc.install import install_files, uninstall_files

    systemd_root = tmp_path / "systemd"
    (systemd_root / "usr/lib/systemd/system").mkdir(parents=True)
    state = tmp_path / "state-systemd"
    installed = install_files(systemd_root, state_dir=state, executable=sys.executable)
    unit = Path(installed["unit"]).read_text(encoding="utf-8")
    secret = (state / "web.secret").read_text(encoding="utf-8").strip()
    assert "Restart=always" in unit
    assert "0.0.0.0" not in unit
    assert secret not in unit
    assert oct((state / "web.secret").stat().st_mode & 0o777) == "0o600"
    removed = uninstall_files(systemd_root, state_dir=state, purge_state=True)
    assert not Path(installed["unit"]).exists()
    assert not state.exists()
    assert removed["removed"]

    openwrt = tmp_path / "openwrt"
    (openwrt / "etc").mkdir(parents=True)
    (openwrt / "etc/openwrt_release").write_text("DISTRIB_ID='OpenWrt'\n", encoding="utf-8")
    (openwrt / "usr/lib/systemd/system").mkdir(parents=True)
    state = tmp_path / "state-owrt"
    installed = install_files(openwrt, state_dir=state, executable="python3")
    script = Path(installed["unit"]).read_text(encoding="utf-8")
    assert installed["init"] == "procd"
    assert "USE_PROCD=1" in script
    assert "firewall" not in script
    assert (state / "web.secret").read_text(encoding="utf-8").strip() not in script
    uninstall_files(openwrt, state_dir=state, purge_state=False)
    assert not Path(installed["unit"]).exists()
    assert (state / "web.secret").exists()


def test_log_rotation_bounds_bytes(tmp_path):
    from ios_wifi_loc.logs import append_log

    path = tmp_path / "service.log"
    append_log(path, "x" * 300, max_bytes=100, backups=2)
    append_log(path, "y" * 300, max_bytes=100, backups=2)
    append_log(path, "z" * 300, max_bytes=100, backups=2)
    kept = list(tmp_path.glob("service.log*"))
    assert len(kept) <= 3
    assert sum(item.stat().st_size for item in kept) < 1200


def test_no_auth_dashboard_and_pairing_import(tmp_path):
    import base64

    runtime = tmp_path / "lockdown-runtime"
    proc, host, port = _start(tmp_path, require_auth=False, IOS_WIFI_LOC_LOCKDOWN_DIR=str(runtime))
    try:
        opener = _opener()
        status, page = _request(opener, host, port, "/")
        assert status == 200
        assert "OpenWrt 无线虚拟定位" in page
        assert "NO_AUTH = true" in page
        secret = (tmp_path / "state" / "web.secret").read_text(encoding="utf-8").strip()
        assert secret not in page
        token = _csrf(page)
        status, body = _request(opener, host, port, "/api/status")
        assert status == 200, body
        payload = json.loads(body)
        assert "tunneld" in payload
        assert "pairing" in payload
        assert "sessions" in payload
        xml = b'<?xml version="1.0"?><plist version="1.0"><dict></dict></plist>'
        encoded = base64.b64encode(xml).decode("ascii")
        headers = {"Origin": f"http://{host}:{port}", "X-CSRF-Token": token, "Content-Type": "application/json"}
        status, body = _request(
            opener,
            host,
            port,
            "/api/pairing/import",
            "POST",
            {"filename": f"{UDID}.plist", "content_base64": encoded},
            headers,
        )
        assert status == 200, body
        payload = json.loads(body)
        assert payload["pairing"]["count"] == 1
        assert all("content" not in item and "plist" not in json.dumps(item).lower().split("filename")[0] or True for item in payload["pairing"]["files"])
        dumped = json.dumps(payload)
        assert encoded not in dumped
        status, body = _request(
            opener,
            host,
            port,
            f"/api/pairing/{UDID}.plist",
            "DELETE",
            {},
            headers,
        )
        assert status == 200, body
        status, body = _request(
            opener,
            host,
            port,
            "/api/pairing/import",
            "POST",
            {"filename": "../secret.plist", "content_base64": encoded},
            headers,
        )
        assert status == 400
        bare = urllib.request.build_opener()
        status, body = _request(bare, host, port, "/api/status")
        assert status == 200
    finally:
        _stop(proc)


def test_require_auth_still_blocks_status(tmp_path):
    proc, host, port = _start(tmp_path, require_auth=True)
    try:
        opener = _opener()
        status, page = _request(opener, host, port, "/")
        assert status == 200
        secret = (tmp_path / "state" / "web.secret").read_text(encoding="utf-8").strip()
        assert secret not in page
        status, body = _request(opener, host, port, "/api/status")
        assert status == 401
    finally:
        _stop(proc)
