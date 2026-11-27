from __future__ import annotations

from pathlib import Path

from ios_wifi_loc import __version__
from ios_wifi_loc.install import install_files
from ios_wifi_loc.service import DEFAULT_PORT
from ios_wifi_loc.watchdog import classify_tunnel
from ios_wifi_loc.web_page import render_page

UDID = "0123456789abcdef0123456789abcdef01234567"


def test_version_and_default_port():
    assert __version__ == "0.5.17"
    assert DEFAULT_PORT == 19443
    html = render_page("csrf", no_auth=True)
    assert "47321" not in html
    assert "等待 Wi-Fi / 隧道恢复后自动重连…" in html
    assert "v0.5.17" in html
    assert html.index('id="map"') < html.index('id="device-select"')
    assert "opt.textContent = deviceTitle(item);" in html
    assert "deviceTitle(item) + \" · \" + deviceStatusText" not in html
    assert "已回到当前保存位置" in html
    assert "已回到默认位置（东京）" in html
    assert "Only secure origins are allowed" not in html
    assert "浏览器仅在 HTTPS 下允许获取本机 GPS" not in html
    assert "一键安装：地图分享定位" in html
    assert "一键安装：恢复真实定位" in html
    assert "https://www.icloud.com/shortcuts/" in html
    assert "pair-group" in html
    assert "共享系统配置" not in html


def test_install_units_embed_port_19443_and_honor_override(tmp_path):
    openwrt = tmp_path / "openwrt"
    (openwrt / "etc").mkdir(parents=True)
    (openwrt / "etc/openwrt_release").write_text("DISTRIB_ID='OpenWrt'\n", encoding="utf-8")
    installed = install_files(openwrt, state_dir=tmp_path / "state-owrt", executable="python3")
    script = Path(installed["unit"]).read_text(encoding="utf-8")
    assert installed["port"] == 19443
    assert "--port 19443" in script
    assert "47321" not in script

    systemd = tmp_path / "systemd"
    (systemd / "usr/lib/systemd/system").mkdir(parents=True)
    installed = install_files(
        systemd,
        state_dir=tmp_path / "state-sys",
        executable="python3",
        port=18080,
    )
    unit = Path(installed["unit"]).read_text(encoding="utf-8")
    assert installed["port"] == 18080
    assert "--port 18080" in unit
    assert "19443" not in unit


def test_classify_tunnel_missing_and_changed():
    started = ("fd53::1", 50001)
    missing = {"reachable": True, "tunnels": []}
    assert classify_tunnel(UDID, started, missing) == "missing"
    changed = {
        "reachable": True,
        "tunnels": [{"udid": UDID, "address": "fd53::1", "port": 50002}],
    }
    assert classify_tunnel(UDID, started, changed) == "changed"
    same = {
        "reachable": True,
        "tunnels": [{"udid": UDID, "address": "fd53::1", "port": 50001}],
    }
    assert classify_tunnel(UDID, started, same) is None
    assert classify_tunnel(UDID, started, {"reachable": False, "tunnels": []}) == "unreachable"


from ios_wifi_loc.service import ServiceError, normalize_icloud_shortcut_url
from ios_wifi_loc.session import (
    Outcome,
    forget_desired_target,
    list_enabled_desired_targets,
    remember_desired_target,
    resume_desired_targets,
)
from ios_wifi_loc.state import StateStore
import pytest


def test_icloud_shortcut_url_and_ui_copy():
    assert normalize_icloud_shortcut_url("") == ""
    assert normalize_icloud_shortcut_url("https://www.icloud.com/shortcuts/abc123XYZ/") == "https://www.icloud.com/shortcuts/abc123XYZ"
    with pytest.raises(ServiceError):
        normalize_icloud_shortcut_url("https://example.com/shortcuts/abc")


def test_desired_targets_persist_across_reload_and_resume_until_clear(tmp_path):
    store = StateStore(tmp_path / "state")
    remember_desired_target(
        store,
        udid=UDID,
        lat="35.6812",
        lon="139.7671",
        profile="ios17",
        transport="mobdev2",
        host=None,
    )
    reloaded = StateStore(tmp_path / "state")
    items = list_enabled_desired_targets(reloaded.load())
    assert len(items) == 1
    assert items[0]["udid"] == UDID
    assert items[0]["lat"] == "35.6812"
    assert items[0]["lon"] == "139.7671"
    assert items[0]["profile"] == "ios17"
    assert items[0]["enabled"] is True
    assert items[0]["transport"] == "mobdev2"

    called = []

    def apply(item):
        called.append(dict(item))
        return Outcome(True, "SET_HOLDING", 0, "ok", {"udid": item["udid"]})

    results = resume_desired_targets(reloaded, "pymobiledevice3", apply=apply, timeout=1, grace=0.2)
    assert results and results[0]["ok"] is True and results[0]["action"] == "resumed"
    assert called and called[0]["udid"] == UDID and called[0]["lat"] == "35.6812"

    # Already holding should not spawn again.
    called.clear()
    results = resume_desired_targets(
        reloaded,
        "pymobiledevice3",
        apply=apply,
        holding=lambda item, session: True,
        timeout=1,
        grace=0.2,
    )
    assert results[0]["action"] == "already_holding"
    assert called == []

    forget_desired_target(reloaded, UDID)
    after = StateStore(tmp_path / "state")
    assert list_enabled_desired_targets(after.load()) == []
    called.clear()
    results = resume_desired_targets(after, "pymobiledevice3", apply=apply, timeout=1, grace=0.2)
    assert results == []
    assert called == []


def test_desired_targets_backfill_from_session(tmp_path):
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["sessions"] = {
        UDID: {"udid": UDID, "latitude": "40.7128", "longitude": "-74.0060", "profile": "ios17", "transport": "usbmux"}
    }
    store.save(data)
    again = StateStore(tmp_path / "state")
    items = list_enabled_desired_targets(again.load())
    assert items[0]["lat"] == "40.7128"
    assert items[0]["lon"] == "-74.0060"
    assert items[0]["transport"] == "usbmux"
