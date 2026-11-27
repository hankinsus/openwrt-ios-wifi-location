from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path

import pytest

from ios_wifi_loc import __version__
from ios_wifi_loc.session import (
    Outcome,
    backfill_desired_targets,
    clear_location,
    desired_target_active,
    forget_desired_target,
    hold_spawn_lock,
    list_enabled_desired_targets,
    remember_desired_target,
    resume_desired_targets,
    restore_desired_loop,
)
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page

UDID = "00008150-001A218E3A123801"


def _select(store: StateStore, udid: str = UDID) -> None:
    data = store.load()
    data["selected"] = {
        "udid": udid,
        "transport": "mobdev2",
        "host": "192.0.2.10",
        "connection": "wifi",
    }
    store.save(data)


def _remember(store: StateStore) -> None:
    remember_desired_target(
        store,
        udid=UDID,
        lat="31.2304",
        lon="121.4737",
        profile="ios17",
        transport="mobdev2",
        host="192.0.2.10",
    )


def test_version_is_049():
    assert __version__ == "0.4.10"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.10" in html
    assert "OpenWrt 无线虚拟定位 · v0.4.10" in html
    assert "v0.4.8" not in html


def test_forget_leaves_tombstone_that_blocks_session_backfill(tmp_path):
    store = StateStore(tmp_path / "state")
    _remember(store)
    forget_desired_target(store, UDID)
    data = store.load()
    target = (data.get("desired_targets") or {}).get(UDID)
    assert isinstance(target, dict)
    assert target.get("enabled") is False
    assert target.get("cleared") is True
    assert desired_target_active(data, UDID) is False
    assert list_enabled_desired_targets(data) == []

    data["sessions"] = {
        UDID: {
            "udid": UDID,
            "latitude": "31.2304",
            "longitude": "121.4737",
            "profile": "ios17",
            "holding": True,
        }
    }
    backfill_desired_targets(data)
    assert desired_target_active(data, UDID) is False
    assert list_enabled_desired_targets(data) == []
    called = []

    def apply(item):
        called.append(dict(item))
        return Outcome(True, "SET_HOLDING", 0, "ok")

    store.save(data)
    results = resume_desired_targets(store, "pymobiledevice3", apply=apply, timeout=1, grace=0.2)
    assert results == []
    assert called == []


def test_clear_forgets_desired_even_if_upstream_clear_fails(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state")
    _select(store)
    _remember(store)
    monkeypatch.setattr("ios_wifi_loc.session.query_tunneld", lambda: {"reachable": False})
    outcome = clear_location(store, "pymobiledevice3", timeout=2, allow_usb=True, profile="ios17")
    assert outcome.ok is False
    data = store.load()
    assert desired_target_active(data, UDID) is False
    assert list_enabled_desired_targets(data) == []
    called = []

    def apply(item):
        called.append(dict(item))
        return Outcome(True, "SET_HOLDING", 0, "ok")

    results = resume_desired_targets(store, "pymobiledevice3", apply=apply, timeout=1, grace=0.2)
    assert results == []
    assert called == []


def test_restore_loop_cannot_respawn_during_or_after_clear(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state")
    _select(store)
    _remember(store)

    applied: list[float] = []

    def apply(item):
        applied.append(time.monotonic())
        return Outcome(True, "SET_HOLDING", 0, "ok", {"udid": item["udid"]})

    stop = threading.Event()
    thread = threading.Thread(
        target=restore_desired_loop,
        args=(stop, store, "pymobiledevice3"),
        kwargs={
            "interval": 0.05,
            "apply": apply,
            "timeout": 2,
            "grace": 0.2,
            "holding": lambda _item, _session: False,
        },
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not applied:
        time.sleep(0.02)
    assert applied, "restore_desired_loop should apply while the target is still desired"
    before = len(applied)

    started_clear = threading.Event()

    class Result:
        ok = True
        error = None
        timed_out = False
        returncode = 0
        stderr = ""
        stdout = ""

    def slow_run(argv, timeout=None, **kwargs):
        started_clear.set()
        # Stay inside clear_location's hold_spawn_lock so a concurrent
        # restore_desired_loop tick cannot spawn while clear is in flight.
        time.sleep(0.45)
        return Result()

    monkeypatch.setattr(
        "ios_wifi_loc.session.query_tunneld",
        lambda: {"reachable": True, "tunnels": []},
    )
    monkeypatch.setattr("ios_wifi_loc.session.run", slow_run)

    outcome = clear_location(store, "pymobiledevice3", timeout=5, allow_usb=True, profile="ios17")
    assert outcome.ok, (outcome.code, outcome.summary)
    assert started_clear.is_set()
    time.sleep(0.35)
    after = len(applied)
    stop.set()
    thread.join(timeout=3)
    assert after == before, (
        f"restore_desired_loop applied {after - before} extra time(s) during/after clear; "
        "a new _hold would have been spawned on the device"
    )
    data = store.load()
    assert desired_target_active(data, UDID) is False
    assert list_enabled_desired_targets(data) == []
    backfill_desired_targets(data)
    assert list_enabled_desired_targets(data) == []
    called = []

    def apply_again(item):
        called.append(dict(item))
        return Outcome(True, "SET_HOLDING", 0, "ok")

    results = resume_desired_targets(store, "pymobiledevice3", apply=apply_again, timeout=1, grace=0.2)
    assert results == []
    assert called == []


def test_clear_blocks_restore_on_shared_hold_spawn_lock(tmp_path):
    store = StateStore(tmp_path / "state")
    _select(store)
    _remember(store)
    release = threading.Event()
    entered = threading.Event()
    called = []

    def apply(item):
        called.append(dict(item))
        return Outcome(True, "SET_HOLDING", 0, "ok")

    def holder():
        with hold_spawn_lock(store, UDID):
            entered.set()
            release.wait(timeout=2)

    worker = threading.Thread(target=holder, daemon=True)
    worker.start()
    assert entered.wait(timeout=2)

    finished = threading.Event()
    results: list[list] = []

    def resume():
        results.append(
            resume_desired_targets(store, "pymobiledevice3", apply=apply, timeout=1, grace=0.2)
        )
        finished.set()

    resumer = threading.Thread(target=resume, daemon=True)
    resumer.start()
    time.sleep(0.2)
    assert not finished.is_set(), "resume must wait for the same hold_spawn_lock used by clear"
    assert called == []
    forget_desired_target(store, UDID)
    release.set()
    assert finished.wait(timeout=2)
    worker.join(timeout=2)
    resumer.join(timeout=2)
    assert called == []
    assert results and all(item.get("code") == "NOT_DESIRED" or item.get("action") == "skipped" for item in results[0])


def test_hold_spawn_lock_is_reentrant(tmp_path):
    store = StateStore(tmp_path / "state")
    seen = []
    with hold_spawn_lock(store, UDID):
        seen.append("outer")
        with hold_spawn_lock(store, UDID):
            seen.append("inner")
    assert seen == ["outer", "inner"]


def test_simulate_api_matches_pymobiledevice3_11631():
    from ios_wifi_loc import simulate_loop

    text = Path(simulate_loop.__file__).read_text(encoding="utf-8")
    assert "get_tunneld_device_by_udid" in text
    assert "async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as sim" in text
    assert "await sim.set(" in text
    assert "create_using_rsd" not in text
    pymobiledevice3 = pytest.importorskip("pymobiledevice3")
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
    from pymobiledevice3.tunneld.api import get_tunneld_device_by_udid

    assert inspect.iscoroutinefunction(get_tunneld_device_by_udid)
    params = inspect.signature(get_tunneld_device_by_udid).parameters
    assert "udid" in params
    assert "tunneld_address" in params
    assert inspect.iscoroutinefunction(LocationSimulation.set)
    assert hasattr(DvtProvider, "__aenter__")
    assert hasattr(LocationSimulation, "__aenter__")
    _ = pymobiledevice3
