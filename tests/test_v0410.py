from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.runner import (
    HolderProcessCounts,
    is_holder_command,
    is_simulate_command,
    is_watchdog_command,
)
from ios_wifi_loc.session import Outcome, remember_desired_target, resume_desired_targets
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page

UDID = "00008150-001A218E3A123801"


def _counts(watchdog: int, simulate: int) -> HolderProcessCounts:
    return HolderProcessCounts(
        watchdog=list(range(1000, 1000 + watchdog)),
        simulate=list(range(2000, 2000 + simulate)),
    )


def _store(tmp_path, *, pid=None, child_pid=None, holding: bool = True) -> StateStore:
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["selected"] = {
        "udid": UDID,
        "transport": "mobdev2",
        "host": "192.0.2.10",
        "connection": "wifi",
    }
    if pid is not None or child_pid is not None:
        data["sessions"] = {
            UDID: {
                "udid": UDID,
                "pid": pid,
                "watchdog_pid": pid,
                "child_pid": child_pid,
                "profile": "ios17",
                "latitude": "39.7488999",
                "longitude": "-75.5488999",
                "holding": holding,
                "watchdog_active": bool(pid),
            }
        }
    store.save(data)
    remember_desired_target(
        store,
        udid=UDID,
        lat="39.7488999",
        lon="-75.5488999",
        profile="ios17",
        transport="mobdev2",
        host="192.0.2.10",
    )
    return store


def _resume(store, monkeypatch, counts: HolderProcessCounts, *, is_holding: bool | None = True):
    monkeypatch.setattr(
        "ios_wifi_loc.session.holder_process_counts",
        lambda **_kwargs: counts,
    )
    called: list[dict] = []

    def apply(item):
        called.append(dict(item))
        return Outcome(True, "SET_HOLDING", 0, "ok", {"udid": item["udid"]})

    kwargs = {"apply": apply, "timeout": 1, "grace": 0.2}
    if is_holding is not None:
        kwargs["holding"] = lambda _item, _session: is_holding
    results = resume_desired_targets(store, "pymobiledevice3", **kwargs)
    return results, called


def test_version_is_0410():
    assert __version__ == "0.4.14"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.14" in html
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位" in html and "v0.4.14" in html
    assert "OpenWrt 无线虚拟定位" not in html
    assert "v0.4.9" not in html


def test_holder_commands_are_classified_without_changing_reap_semantics():
    hold = "python3 -m ios_wifi_loc --state-dir /etc/ios-wifi-loc _hold --udid " + UDID
    sim = "python3 -m ios_wifi_loc --state-dir /etc/ios-wifi-loc _simulate --udid " + UDID
    cli = "pymobiledevice3 developer dvt simulate-location set --tunnel " + UDID + " -- 39.74 -75.54"
    assert is_watchdog_command(hold) and not is_simulate_command(hold)
    assert is_simulate_command(sim) and not is_watchdog_command(sim)
    assert is_simulate_command(cli) and not is_watchdog_command(cli)
    assert is_holder_command(hold) and is_holder_command(sim) and is_holder_command(cli)
    family = _counts(1, 1)
    assert family.is_healthy_family() is True
    assert _counts(1, 0).is_healthy_family() is True
    assert _counts(2, 1).is_healthy_family() is False
    assert _counts(1, 2).is_healthy_family() is False
    assert _counts(0, 1).is_healthy_family() is False


def test_resume_already_holding_for_healthy_hold_plus_simulate(tmp_path, monkeypatch):
    store = _store(tmp_path, pid=14684, child_pid=14686)
    results, called = _resume(store, monkeypatch, _counts(1, 1), is_holding=True)
    assert results and results[0]["action"] == "already_holding"
    assert results[0]["ok"] is True
    assert called == []


def test_resume_already_holding_while_watchdog_starts_without_child(tmp_path, monkeypatch):
    store = _store(tmp_path, pid=14684, child_pid=None)
    results, called = _resume(store, monkeypatch, _counts(1, 0), is_holding=True)
    assert results and results[0]["action"] == "already_holding"
    assert called == []


def test_resume_replaces_duplicate_watchdogs(tmp_path, monkeypatch):
    store = _store(tmp_path, pid=14684, child_pid=14686)
    results, called = _resume(store, monkeypatch, _counts(2, 1), is_holding=True)
    assert called and called[0]["udid"] == UDID
    assert results[0]["action"] == "resumed"
    assert results[0]["ok"] is True


def test_resume_replaces_duplicate_simulate_children(tmp_path, monkeypatch):
    store = _store(tmp_path, pid=14684, child_pid=14686)
    results, called = _resume(store, monkeypatch, _counts(1, 2), is_holding=True)
    assert called, results
    assert results[0]["action"] == "resumed"


def test_resume_replaces_orphan_simulate_when_watchdog_is_dead(tmp_path, monkeypatch):
    store = _store(tmp_path, pid=14684, child_pid=14686, holding=False)
    results, called = _resume(store, monkeypatch, _counts(0, 1), is_holding=False)
    assert called, results
    assert results[0]["action"] == "resumed"
