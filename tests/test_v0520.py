from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ios_wifi_loc import __version__
from ios_wifi_loc.service import Console
from ios_wifi_loc.session import forget_desired_target, remember_desired_target
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page

UDID_15 = "17d53308c7d4237c1f09aadc6458baefde615e45"
UDID_16 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
UDID_17 = "00008150-0015543914F0C01C"
HOST = "fe80::c70:fec:e827:5639%br-lan"
LAT = "35.681200"
LON = "139.767100"


def test_version_is_0520():
    assert __version__ == "0.5.20"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.20" in html
    assert "v0.5.19" not in html


def test_page_keeps_ios17_tunnel_copy_and_adds_pre17_labels():
    html = render_page("csrf", no_auth=True)
    assert 'picked.textContent = discovered ? "已发现" : "未发现"' in html
    assert 'pre17LocationActive(item) ? "已定位" : ""' in html
    assert 'picked.textContent = connected ? "已连接" : "未连接"' in html
    assert "current.tunnel_connected || current.tunnel_ready" in html
    assert ">未连接</span>" in html
    for label in (
        "已连接",
        "未连接",
        "等待连接",
        "等待隧道",
        "隧道就绪",
        "模拟中",
        "等待隧道恢复自动重连…",
        "等待 Wi-Fi / 隧道恢复后自动重连…",
        "保持中（自动重连已开启，已重连 ",
    ):
        assert label in html


def _save_device(store: StateStore, *, udid: str, version: str | None, host: str | None, located: bool = False, cleared: bool = False, profile: str = "pre17") -> None:
    data = store.load()
    item = {
        "udid": udid,
        "name": "iPhone",
        "product_version": version,
        "transport": "mobdev2",
        "connection": "wifi",
        "source": "bonjour_mobdev2" if host else "pairing",
        "host": host,
    }
    data["discovery"] = [item]
    data["device_names"] = {udid: {"name": "iPhone", "product_version": version}} if version else {}
    data["selected"] = {
        "udid": udid,
        "transport": "mobdev2",
        "host": host,
        "name": "iPhone",
        "product_version": version,
        "connection": "wifi",
    }
    data["sessions"] = {}
    data["session"] = None
    data["desired_targets"] = {}
    store.save(data)
    if not located and not cleared:
        return
    remember_desired_target(store, udid=udid, lat=LAT, lon=LON, profile=profile, transport="mobdev2", host=host)
    data = store.load()
    data["sessions"] = {
        udid: {
            "udid": udid,
            "profile": profile,
            "latitude": LAT,
            "longitude": LON,
            "holding": False,
            "pid": None,
        }
    }
    data["session"] = dict(data["sessions"][udid])
    store.save(data)
    if not cleared:
        return
    forget_desired_target(store, udid)
    data = store.load()
    sessions = dict(data.get("sessions") or {})
    sessions.pop(udid, None)
    data["sessions"] = sessions
    data["session"] = None
    store.save(data)


def _payload(store: StateStore) -> dict:
    return Console(store, "pymobiledevice3", "secret", require_auth=False, restore=False).payload()


def _card(device: dict, **extra) -> dict:
    payload = {
        "tunneld": {"reachable": True, "tunnels": []},
        "devices": [device],
        "selected": {"udid": device["udid"], "product_version": device.get("product_version")},
        "device_names": {},
        "sessions": [],
        "desired_targets": [],
        "session": None,
    }
    payload.update(extra)
    return payload


def _paint_cards(payloads: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    html = render_page("csrf", no_auth=True)
    start = html.index("function isGenericDeviceName(")
    end = html.index("function esc(")
    script = """
var lastPayload = {};
var elements = {};
function make(id) {
  var node = {
    id: id,
    hidden: false,
    textContent: "",
    className: "",
    dataset: {},
    children: [],
    setAttribute: function () {},
    getAttribute: function () { return null; },
    appendChild: function (child) { this.children.push(child); return child; },
    replaceChildren: function () { this.children.length = 0; }
  };
  if (id) elements[id] = node;
  return node;
}
["device-select","device-select-list","device-select-btn","device-info","device-status","device-info-picked","device-info-title","device-info-udid","device-info-host"].forEach(make);
var document = {
  getElementById: function (id) { return elements[id] || null; },
  createElement: function () { return make(""); },
  createTextNode: function (text) { return { textContent: String(text) }; }
};
function $(id) { return document.getElementById(id); }
function chooseDevice() {}
""" + html[start:end] + """
const fs = require("fs");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map(function (payload) {
  lastPayload = payload;
  Object.keys(elements).forEach(function (id) {
    const node = elements[id];
    node.hidden = false;
    node.textContent = "";
    node.className = "";
    node.children.length = 0;
  });
  elements["device-select-list"].hidden = true;
  paintDeviceSelect(payload);
  const picked = elements["device-info-picked"];
  const box = elements["device-status"];
  return {
    picked: picked.textContent,
    pickedClass: picked.className,
    statuses: box.children.map(function (child) { return child.textContent; }),
    statusClass: box.children.map(function (child) { return child.className; })
  };
});
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run([node, "-e", script], input=json.dumps(payloads), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_pre17_labels_follow_discovery_and_active_location(tmp_path, monkeypatch):
    tunnels = {"reachable": True, "tunnels": []}

    def query():
        return {"reachable": tunnels["reachable"], "tunnels": list(tunnels["tunnels"]), "error": None}

    monkeypatch.setattr("ios_wifi_loc.session.query_tunneld", query)

    discovered = StateStore(tmp_path / "discovered")
    _save_device(discovered, udid=UDID_15, version="15.8.8", host=HOST)
    discovered_payload = _payload(discovered)
    discovered_device = discovered_payload["devices"][0]
    assert discovered_device["host"] == HOST
    assert discovered_device["product_version"] == "15.8.8"
    assert discovered_device.get("desired") is not True
    assert discovered_device.get("latitude") in (None, "")
    assert discovered_device.get("tunnel_connected") is False

    missing = StateStore(tmp_path / "missing")
    _save_device(missing, udid=UDID_15, version="15.8.8", host=None)
    missing_payload = _payload(missing)
    missing_device = missing_payload["devices"][0]
    assert not missing_device.get("host")
    assert missing_device["product_version"] == "15.8.8"

    located = StateStore(tmp_path / "located")
    _save_device(located, udid=UDID_15, version="15.8.8", host=HOST, located=True)
    located_payload = _payload(located)
    located_device = located_payload["devices"][0]
    assert located_device["desired"] is True
    assert located_device["latitude"] == LAT
    assert located_device["longitude"] == LON
    assert located_device["host"] == HOST
    assert any(item.get("profile") == "pre17" for item in located_payload["desired_targets"])

    cleared = StateStore(tmp_path / "cleared")
    _save_device(cleared, udid=UDID_15, version="15.8.8", host=HOST, located=True, cleared=True)
    cleared_payload = _payload(cleared)
    cleared_device = cleared_payload["devices"][0]
    assert cleared_device["host"] == HOST
    assert cleared_device["product_version"] == "15.8.8"
    assert cleared_device.get("desired") is not True
    assert cleared_device.get("latitude") in (None, "")
    assert cleared_device.get("longitude") in (None, "")
    assert all(item.get("udid") != UDID_15 for item in cleared_payload["desired_targets"])

    ios_idle = StateStore(tmp_path / "ios-idle")
    _save_device(ios_idle, udid=UDID_17, version="18.6.1", host=HOST, profile="ios17")
    ios_idle_payload = _payload(ios_idle)

    ios_located = StateStore(tmp_path / "ios-located")
    _save_device(ios_located, udid=UDID_17, version="18.6.1", host=HOST, located=True, profile="ios17")
    ios_located_payload = _payload(ios_located)
    ios_located_device = ios_located_payload["devices"][0]
    assert ios_located_device["desired"] is True
    assert ios_located_device["latitude"] == LAT
    assert ios_located_device.get("holding") is False
    assert ios_located_device.get("session_alive") is False

    tunnels["tunnels"] = [{"udid": UDID_17, "address": "fd00::1", "port": 49151}]
    ios_ready = StateStore(tmp_path / "ios-ready")
    _save_device(ios_ready, udid=UDID_17, version="27.2.1", host=HOST, profile="ios17")
    ios_ready_payload = _payload(ios_ready)
    assert ios_ready_payload["devices"][0]["tunnel_connected"] is True
    assert ios_ready_payload["devices"][0]["tunnel_ready"] is True
    tunnels["tunnels"] = []
    tunnels["reachable"] = False
    ios_down = StateStore(tmp_path / "ios-down")
    _save_device(ios_down, udid=UDID_17, version="17.0", host=HOST, profile="ios17")
    ios_down_payload = _payload(ios_down)
    tunnels["reachable"] = True

    cached_version = _card(
        {"udid": UDID_15, "name": "iPhone", "host": HOST},
        device_names={UDID_15: {"name": "iPhone", "product_version": "15.8.8"}},
        selected={"udid": UDID_15},
    )
    profile_only = _card(
        {"udid": UDID_16, "name": "iPhone", "host": HOST, "latitude": LAT, "longitude": LON, "desired": True},
        sessions=[{"udid": UDID_16, "profile": "pre17", "latitude": LAT, "longitude": LON}],
        desired_targets=[{"udid": UDID_16, "profile": "pre17", "enabled": True, "latitude": LAT, "longitude": LON}],
        selected={"udid": UDID_16},
    )
    profile_only_offline = _card(
        {"udid": UDID_16, "name": "iPhone", "latitude": LAT, "longitude": LON, "desired": True},
        sessions=[{"udid": UDID_16, "profile": "pre17", "latitude": LAT, "longitude": LON}],
        selected={"udid": UDID_16},
    )
    leftover = _card(
        {
            "udid": UDID_15,
            "product_version": "15.8.8",
            "host": HOST,
            "latitude": LAT,
            "longitude": LON,
            "desired": False,
        }
    )
    blank_host = _card({"udid": UDID_15, "product_version": "16.7.1", "host": "   "})
    boundary_16 = _card({"udid": UDID_16, "product_version": "16.0", "host": HOST})
    boundary_17 = _card({"udid": UDID_17, "product_version": "17.0", "host": HOST, "tunnel_connected": False, "tunnel_ready": False})
    simulating = _card(
        {
            "udid": UDID_17,
            "product_version": "18.6.1",
            "host": HOST,
            "holding": True,
            "session_alive": True,
            "latitude": "35.68",
            "longitude": "139.77",
            "tunnel_connected": True,
            "tunnel_ready": True,
        }
    )
    holding = _card(
        {
            "udid": UDID_17,
            "product_version": "18.6.1",
            "host": HOST,
            "holding": True,
            "session_alive": True,
            "watchdog_active": True,
            "reconnect_count": 2,
            "latitude": "35.68",
            "longitude": "139.77",
            "tunnel_connected": True,
            "tunnel_ready": True,
        }
    )
    reconnecting = _card(
        {
            "udid": UDID_17,
            "product_version": "18.6.1",
            "host": HOST,
            "waiting_reconnect": True,
            "watchdog_active": True,
            "tunnel_connected": False,
            "tunnel_ready": False,
        }
    )
    waiting_wifi = _card(
        {
            "udid": UDID_17,
            "product_version": "27.2.1",
            "host": HOST,
            "waiting_for_wifi": True,
            "watchdog_active": True,
            "tunnel_connected": False,
            "tunnel_ready": False,
        }
    )

    named = [
        ("discovered", discovered_payload, "已发现", "badge-connected", []),
        ("not-discovered", missing_payload, "未发现", "badge-disconnected", []),
        ("located", located_payload, "已发现", "badge-connected", ["已定位"]),
        ("cleared", cleared_payload, "已发现", "badge-connected", []),
        ("cached-version", cached_version, "已发现", "badge-connected", []),
        ("profile-located", profile_only, "已发现", "badge-connected", ["已定位"]),
        ("profile-offline-located", profile_only_offline, "未发现", "badge-disconnected", ["已定位"]),
        ("leftover-coords", leftover, "已发现", "badge-connected", []),
        ("blank-host", blank_host, "未发现", "badge-disconnected", []),
        ("ios16", boundary_16, "已发现", "badge-connected", []),
        ("ios17-boundary", boundary_17, "未连接", "badge-disconnected", ["等待连接"]),
        ("ios17-idle", ios_idle_payload, "未连接", "badge-disconnected", ["等待连接"]),
        ("ios17-desired-without-holder", ios_located_payload, "未连接", "badge-disconnected", ["等待连接"]),
        ("ios17-tunnel-ready", ios_ready_payload, "已连接", "badge-connected", ["隧道已就绪"]),
        ("ios17-tunneld-down", ios_down_payload, "未连接", "badge-disconnected", ["等待隧道"]),
        ("ios17-simulating", simulating, "已连接", "badge-connected", ["模拟中 35.68, 139.77"]),
        ("ios17-holding", holding, "已连接", "badge-connected", ["保持中（自动重连已开启，已重连 2 次） · 35.68, 139.77"]),
        ("ios17-reconnect", reconnecting, "未连接", "badge-disconnected", ["等待隧道恢复自动重连…"]),
        ("ios17-wait-wifi", waiting_wifi, "未连接", "badge-disconnected", ["等待 Wi-Fi / 隧道恢复后自动重连…"]),
    ]

    painted = _paint_cards([item[1] for item in named])
    assert len(painted) == len(named)
    for (name, _payload_item, picked, picked_class, statuses), got in zip(named, painted):
        assert got["picked"] == picked, name
        assert picked_class in got["pickedClass"], (name, got)
        assert got["statuses"] == statuses, (name, got)
        if statuses == ["已定位"]:
            assert got["statusClass"] == ["badge badge-on"], (name, got)
        if name == "cleared":
            assert got["statuses"] == []
        if name.startswith("ios17"):
            assert "已发现" not in got["picked"]
            assert "未发现" not in got["picked"]
            assert "已定位" not in "".join(got["statuses"])
