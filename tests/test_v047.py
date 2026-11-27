from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ios_wifi_loc import __version__
from ios_wifi_loc.install import _openrc_tunneld_unit, _openrc_unit, _procd_unit, _systemd_tunneld_unit, _systemd_unit
from ios_wifi_loc.runner import pid_alive, pids_matching
from ios_wifi_loc.session import (
    reap_stray_holders,
    remember_desired_target,
    resume_desired_targets,
    set_location,
    stop_all_holders,
)
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page

UDID = "00008150-001A218E3A123801"
ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["selected"] = {"udid": UDID, "transport": "mobdev2", "connection": "wifi"}
    store.save(data)
    return store


def _orphan(*tokens: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", *tokens],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_dead(pids: list[int], timeout: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(pid_alive(pid) for pid in pids):
            return True
        time.sleep(0.05)
    return not any(pid_alive(pid) for pid in pids)


def test_version_is_047():
    assert __version__ == "0.5.15"
    html = render_page("csrf", no_auth=True)
    assert "v0.5.15" in html
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位" in html and "v0.5.15" in html
    assert "OpenWrt 无线虚拟定位" not in html
    assert "v0.4.6" not in html


def test_ui_footer_and_layer_bar_source():
    html = render_page("csrf", no_auth=True)
    assert 'class="map-shell"' in html
    assert ".map-shell { width:100%; max-width:100%;" in html
    assert "100vw" not in html
    assert ".map-wrap { width:100%; max-width:100%;" in html
    assert "overflow:visible" in html
    assert "left:auto; right:12px;" in html
    assert "max-width:calc(100% - 56px)" in html
    assert "flex-wrap:wrap" in html
    assert "margin:36px 0 24px" in html
    assert ".footer-card { width:100%; max-width:none;" in html
    assert "background:transparent" in html
    assert 'data-layer="satellite"' in html
    assert "卫星" in html and "WGS84" in html and "高德" in html
    assert "彩色" in html and "标准" in html and "暗色" in html
    assert "replace: true" in html


def test_procd_cleans_stale_holders_and_tunneld_on_start_and_stop():
    script = _procd_unit(
        "/usr/bin/ios_wifi_loc",
        Path("/etc/ios-wifi-loc"),
        None,
        "pymobiledevice3",
        require_auth=False,
        port=19443,
    )
    assert "stop_service()" in script
    assert "cleanup_stale_ios_wifi_loc" in script
    assert "cleanup_stale_ios_wifi_holders" in script
    assert "cleanup_stale_ios_wifi_tunneld" in script
    assert "_hold" in script
    assert "simulate-location" in script
    assert "49151" in script
    assert "remote tunneld" in script
    assert "procd_set_param respawn 3600 10 3" in script
    assert script.index("cleanup_stale_ios_wifi_loc") < script.index("procd_open_instance tunneld")
    start = script[script.index("start_service()") : script.index("stop_service()")]
    assert "cleanup_stale_ios_wifi_loc" in start
    systemd = _systemd_unit(
        "/usr/bin/ios_wifi_loc",
        Path("/etc/ios-wifi-loc"),
        None,
        "pymobiledevice3",
        require_auth=False,
        port=19443,
    )
    assert "ExecStartPre=" in systemd and "ExecStop=" in systemd
    assert "cleanup_stale_ios_wifi_holders" in systemd
    tunneld = _systemd_tunneld_unit("pymobiledevice3")
    assert "49151" in tunneld
    assert "cleanup_stale_ios_wifi_tunneld" in tunneld
    openrc = _openrc_unit(
        "/usr/bin/ios_wifi_loc",
        Path("/etc/ios-wifi-loc"),
        None,
        "pymobiledevice3",
        require_auth=False,
        port=19443,
    )
    assert "start_pre()" in openrc and "stop_post()" in openrc
    assert "cleanup_stale_ios_wifi_holders" in openrc
    assert "cleanup_stale_ios_wifi_tunneld" in _openrc_tunneld_unit("pymobiledevice3")


def test_reap_stray_holders_kills_orphan_hold_and_simulate_location(tmp_path: Path):
    store = _store(tmp_path)
    data = store.load()
    data.setdefault("sessions", {})[UDID] = {
        "udid": UDID,
        "pid": 999999,
        "watchdog_pid": 999999,
        "latitude": "31.2",
        "longitude": "121.5",
        "holding": True,
    }
    store.save(data)
    orphans = [
        _orphan("_hold", UDID),
        _orphan("developer", "dvt", "simulate-location", "set", "--tunnel", UDID),
    ]
    pids = [proc.pid for proc in orphans]
    try:
        time.sleep(0.2)
        assert len(pids_matching(udid=UDID, holders=True)) >= 2
        result = reap_stray_holders(store, UDID, timeout=2)
        assert _wait_dead(pids)
        assert pids_matching(udid=UDID, holders=True) == []
        assert result.get("signaled") >= 1
        session = (store.load().get("sessions") or {}).get(UDID) or {}
        assert session.get("pid") is None
        assert session.get("holding") is False
    finally:
        for proc in orphans:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)


def test_stop_all_holders_on_restart_cleans_state_dir_processes(tmp_path: Path):
    store = _store(tmp_path)
    proc = _orphan("_hold", UDID, "--state-dir", str(store.directory))
    try:
        time.sleep(0.2)
        assert proc.pid in pids_matching(udid=UDID, holders=True)
        stop_all_holders(store, timeout=2)
        assert _wait_dead([proc.pid])
        assert pids_matching(udid=UDID, holders=True) == []
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def _patch_hold(monkeypatch, udid: str):
    argv = [sys.executable, "-c", "import time; time.sleep(60)", "_hold", udid]

    def plan(*_args, **_kwargs):
        return (["pymobiledevice3", "developer", "dvt", "simulate-location", "set", "--tunnel", udid], None, {"reachable": True})

    monkeypatch.setattr("ios_wifi_loc.session.query_tunneld", lambda: {"reachable": True, "tunnels": []})
    monkeypatch.setattr("ios_wifi_loc.session._plan_location", plan)
    monkeypatch.setattr(
        "ios_wifi_loc.watchdog.hold_command_argv",
        lambda *_args, **_kwargs: list(argv),
    )
    return argv


def test_set_location_always_replaces_even_when_coordinates_match(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    _patch_hold(monkeypatch, UDID)
    first = set_location(
        store,
        "pymobiledevice3",
        latitude="31.2304",
        longitude="121.4737",
        profile="ios17",
        timeout=2,
        grace=0.2,
        foreground=False,
        allow_usb=True,
        allow_legacy=False,
        replace=True,
    )
    assert first.ok, first.summary
    first_pid = first.details["pid"]
    assert pid_alive(first_pid)
    second = set_location(
        store,
        "pymobiledevice3",
        latitude="31.2304",
        longitude="121.4737",
        profile="ios17",
        timeout=2,
        grace=0.2,
        foreground=False,
        allow_usb=True,
        allow_legacy=False,
        replace=True,
    )
    assert second.ok, second.summary
    second_pid = second.details["pid"]
    try:
        assert second_pid != first_pid
        assert not pid_alive(first_pid)
        assert pid_alive(second_pid)
        assert pids_matching(udid=UDID, holders=True) == [second_pid]
    finally:
        reap_stray_holders(store, UDID, timeout=2)


def test_concurrent_set_location_starts_only_one_hold(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    _patch_hold(monkeypatch, UDID)
    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(
                set_location(
                    store,
                    "pymobiledevice3",
                    latitude="39.9042",
                    longitude="116.4074",
                    profile="ios17",
                    timeout=3,
                    grace=0.2,
                    foreground=False,
                    allow_usb=True,
                    allow_legacy=False,
                    replace=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    try:
        assert errors == []
        assert len(results) == 2
        assert all(item.ok for item in results), [item.summary for item in results]
        live = pids_matching(udid=UDID, holders=True)
        assert len(live) == 1, live
        assert all(pid_alive(item.details["pid"]) is (item.details["pid"] in live) for item in results)
    finally:
        reap_stray_holders(store, UDID, timeout=2)


def test_resume_reapplies_when_two_holds_already_running(tmp_path: Path):
    store = _store(tmp_path)
    remember_desired_target(
        store,
        udid=UDID,
        lat="35.6812",
        lon="139.7671",
        profile="ios17",
        transport="mobdev2",
        host=None,
    )
    orphans = [_orphan("_hold", UDID), _orphan("_hold", UDID)]
    called: list[dict] = []
    try:
        time.sleep(0.2)
        assert len(pids_matching(udid=UDID, holders=True)) >= 2

        def apply(item):
            called.append(dict(item))
            return type("Outcome", (), {"ok": True, "code": "SET_HOLDING", "details": {"udid": item["udid"]}})()

        results = resume_desired_targets(
            store,
            "pymobiledevice3",
            apply=apply,
            holding=lambda item, session: True,
            timeout=1,
            grace=0.2,
        )
        assert called, results
        assert results[0]["ok"] is True
        assert results[0]["action"] != "already_holding"
    finally:
        for proc in orphans:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
