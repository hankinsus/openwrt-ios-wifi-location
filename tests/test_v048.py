from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ios_wifi_loc import __version__
from ios_wifi_loc.runner import is_holder_command
from ios_wifi_loc.simulate_loop import (
    heartbeat_interval,
    prefer_api_heartbeat,
    refresh_location,
    simulate_command_argv,
)
from ios_wifi_loc.upstream import Target
from ios_wifi_loc.watchdog import outage_strikes
from ios_wifi_loc.web_page import render_page

UDID = "00008150-001A218E3A123801"
ROOT = Path(__file__).resolve().parents[1]


def test_version_is_048():
    assert __version__ == "0.4.12"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.12" in html
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位" in html and "v0.4.12" in html
    assert "OpenWrt 无线虚拟定位" not in html
    assert "v0.4.7" not in html


def test_layer_bar_is_compact_top_right():
    html = render_page("csrf", no_auth=True)
    assert "left:auto; right:12px;" in html
    assert "max-width:calc(100% - 56px)" in html
    assert "left:8px; right:8px" not in html


def test_prefer_api_heartbeat_skips_fake_and_legacy(monkeypatch):
    monkeypatch.setenv("IOS_WIFI_LOC_FAKE_LOG", "/tmp/argv.log")
    assert prefer_api_heartbeat("pymobiledevice3", "ios17", True) is False
    monkeypatch.delenv("IOS_WIFI_LOC_FAKE_LOG", raising=False)
    monkeypatch.delenv("IOS_WIFI_LOC_FAKE_DEVICES", raising=False)
    monkeypatch.delenv("IOS_WIFI_LOC_FORCE_CLI", raising=False)
    fake = ROOT / "tests" / "fakes" / "pymobiledevice3"
    assert prefer_api_heartbeat(str(fake), "ios17", True) is False
    assert prefer_api_heartbeat("pymobiledevice3", "pre17", True) is False
    assert prefer_api_heartbeat("pymobiledevice3", "ios17", False) is False
    monkeypatch.setenv("IOS_WIFI_LOC_FORCE_CLI", "1")
    assert prefer_api_heartbeat("pymobiledevice3", "ios17", True) is False


def test_heartbeat_interval_and_outage_strikes(monkeypatch):
    monkeypatch.delenv("IOS_WIFI_LOC_SIM_HEARTBEAT", raising=False)
    monkeypatch.delenv("IOS_WIFI_LOC_WATCHDOG_STRIKES", raising=False)
    assert heartbeat_interval() == 1.0
    assert outage_strikes() == 2
    monkeypatch.setenv("IOS_WIFI_LOC_SIM_HEARTBEAT", "1.5")
    monkeypatch.setenv("IOS_WIFI_LOC_WATCHDOG_STRIKES", "3")
    assert heartbeat_interval() == 1.5
    assert outage_strikes() == 3
    monkeypatch.setenv("IOS_WIFI_LOC_SIM_HEARTBEAT", "0.01")
    assert heartbeat_interval() == 0.3


def test_simulate_argv_and_holder_match():
    argv = simulate_command_argv(
        "python3",
        "/etc/ios-wifi-loc",
        Target(UDID, "mobdev2"),
        "31.2304",
        "121.4737",
        interval=1.0,
    )
    assert "_simulate" in argv
    assert UDID in argv
    assert "31.2304" in argv and "121.4737" in argv
    assert is_holder_command("python3 -m ios_wifi_loc --state-dir /tmp _simulate --udid " + UDID)
    assert is_holder_command("pymobiledevice3 developer dvt simulate-location set --tunnel " + UDID)
    text = Path(__file__).resolve().parents[1].joinpath("src/ios_wifi_loc/simulate_loop.py").read_text(encoding="utf-8")
    assert "wait_return" in text
    assert "clear()" in text
    assert "same" in text.lower() or "同一" in text or "same" in text


def test_refresh_location_repeats_set_on_same_session():
    class FakeSim:
        def __init__(self) -> None:
            self.calls: list[tuple[float, float]] = []

        async def set(self, latitude: float, longitude: float) -> None:
            self.calls.append((latitude, longitude))

        async def clear(self) -> None:
            raise AssertionError("heartbeat must not call clear()")

    sim = FakeSim()
    ticks = {"n": 0}

    async def fake_sleep(_seconds: float) -> None:
        ticks["n"] += 1
        if ticks["n"] >= 3:
            raise asyncio.CancelledError

    stopped = {"flag": False}

    def should_stop() -> bool:
        return stopped["flag"] or ticks["n"] >= 3

    async def runner() -> int:
        try:
            return await refresh_location(sim, 31.2, 121.5, 1.0, should_stop, sleep=fake_sleep)
        except asyncio.CancelledError:
            return len(sim.calls)

    count = asyncio.run(runner())
    assert count >= 3
    assert sim.calls == [(31.2, 121.5)] * len(sim.calls)
    assert all(item == (31.2, 121.5) for item in sim.calls)
