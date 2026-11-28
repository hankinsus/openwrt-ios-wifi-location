from __future__ import annotations


from ios_wifi_loc import __version__
from ios_wifi_loc.service import Console
from ios_wifi_loc.session import merge_known_devices, refresh_devices
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page

UDID_A = "00008150-0015543914F0C01C"
UDID_B = "00008120-001B218E3A123802"
HOST_A = "fe80::1093:44ea:c869:5bd7%br-lan"
HOST_A_NEW = "fe80::aaaa:bbbb:cccc:dddd%br-lan"
HOST_B = "fe80::2%br-lan"


def test_version_is_0414():
    assert __version__ == "0.5.20"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.20" in html
    assert "v0.4.13" not in html


def test_web_page_custom_dropdowns_separate_meta_and_no_auto_scan():
    html = render_page("csrf", no_auth=True)
    assert "添加设备检测" in html
    assert "检测中..." in html
    assert "重新扫描" not in html
    assert "扫描中..." not in html
    assert "<select" not in html
    assert 'id="device-select"' in html
    assert 'id="device-select-btn"' in html
    assert 'id="device-select-list"' in html
    assert 'id="transport-pills"' not in html
    assert 'id="device-info-transport"' not in html
    assert "function setTransport(value)" not in html
    assert 'id="transport"' in html
    assert 'id="transport" value="mobdev2"' in html
    assert "mobdev2（无线）" not in html
    assert "usbmux 网络" not in html
    assert "传输类型" not in html
    assert 'id="device-info-udid"' in html
    assert 'id="device-info-host"' in html
    assert "function closeDeviceMenu()" in html
    assert "function toggleDeviceMenu()" in html
    assert "function fillMetaRow(id, label, value)" in html
    assert 'fillMetaRow("device-info-udid", "UDID"' in html
    assert 'fillMetaRow("device-info-host", "IP"' in html
    assert 'fillMetaRow("device-info-transport"' not in html
    assert 'event.key === "Escape"' in html
    assert "pointerdown" in html
    assert "min-height:44px" in html
    assert "await scan()" not in html
    after = html[html.index("async function afterLogin()") : html.index("CITIES.forEach")]
    assert "await refresh()" in after
    assert "scan(" not in after
    assert 'api("/api/discover"' not in after
    assert "class=\"segment" not in html
    assert "class=\"menu-select-toggle\"" in html


def test_merge_known_devices_adds_updates_and_keeps_unseen():
    existing = [
        {
            "udid": UDID_A,
            "name": "iPhone17 PRO",
            "product_version": "27.2.1",
            "transport": "mobdev2",
            "connection": "wifi",
            "host": HOST_A,
        }
    ]
    incoming = [
        {
            "udid": UDID_A,
            "name": "iPhone",
            "transport": "mobdev2",
            "connection": "wifi",
            "host": HOST_A_NEW,
        },
        {
            "udid": UDID_B,
            "name": "iPhone 16",
            "product_version": "18.6.1",
            "transport": "mobdev2",
            "connection": "wifi",
            "host": HOST_B,
        },
    ]
    merged, added = merge_known_devices(existing, incoming)
    by_id = {item["udid"]: item for item in merged}
    assert added == [UDID_B]
    assert by_id[UDID_A]["name"] == "iPhone17 PRO"
    assert by_id[UDID_A]["host"] == HOST_A_NEW
    assert by_id[UDID_B]["name"] == "iPhone 16"
    kept, added_none = merge_known_devices(merged, [])
    assert added_none == []
    assert {item["udid"] for item in kept} == {UDID_A, UDID_B}
    assert next(item for item in kept if item["udid"] == UDID_A)["host"] == HOST_A_NEW


def test_status_payload_returns_persisted_devices_without_live_scan(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["discovery"] = [
        {
            "udid": UDID_A,
            "name": "iPhone17 PRO",
            "product_version": "27.2.1",
            "transport": "mobdev2",
            "connection": "wifi",
            "host": HOST_A,
            "source": "bonjour",
        }
    ]
    data["device_names"] = {UDID_A: {"name": "iPhone17 PRO", "product_version": "27.2.1"}}
    data["selected"] = {
        "udid": UDID_A,
        "transport": "mobdev2",
        "host": HOST_A,
        "name": "iPhone17 PRO",
        "product_version": "27.2.1",
        "connection": "wifi",
    }
    store.save(data)

    def boom(*args, **kwargs):
        raise AssertionError("status/payload must not start a live device scan")

    monkeypatch.setattr("ios_wifi_loc.session.discover", boom)
    monkeypatch.setattr("ios_wifi_loc.discovery.discover", boom)
    payload = Console(store, "pymobiledevice3", "secret", require_auth=False, restore=False).payload()
    device = next(item for item in payload["devices"] if item["udid"] == UDID_A)
    assert device["name"] == "iPhone17 PRO"
    assert device["product_version"] == "27.2.1"
    assert device["transport"] == "mobdev2"
    assert device["host"] == HOST_A
    assert payload["selected"]["udid"] == UDID_A


def test_refresh_devices_merges_into_persisted_list(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["discovery"] = [
        {
            "udid": UDID_A,
            "name": "iPhone17 PRO",
            "product_version": "27.2.1",
            "transport": "mobdev2",
            "connection": "wifi",
            "host": HOST_A,
        }
    ]
    store.save(data)

    def fake_discover(binary, timeout=0):
        return {
            "devices": [
                {
                    "udid": UDID_A,
                    "name": "iPhone",
                    "transport": "mobdev2",
                    "connection": "wifi",
                    "host": HOST_A_NEW,
                },
                {
                    "udid": UDID_B,
                    "name": "iPhone 16",
                    "product_version": "18.6.1",
                    "transport": "mobdev2",
                    "connection": "wifi",
                    "host": HOST_B,
                },
            ]
        }

    monkeypatch.setattr("ios_wifi_loc.session.discover", fake_discover)
    outcome = refresh_devices(store, "pymobiledevice3", timeout=1)
    assert outcome.ok
    assert outcome.details["added"] == [UDID_B]
    assert outcome.details["added_count"] == 1
    assert outcome.details["known_count"] == 2
    assert "新检测到 1 台设备" in outcome.summary
    saved = {item["udid"]: item for item in store.load()["discovery"]}
    assert saved[UDID_A]["name"] == "iPhone17 PRO"
    assert saved[UDID_A]["host"] == HOST_A_NEW
    assert saved[UDID_B]["name"] == "iPhone 16"

    def empty_discover(binary, timeout=0):
        return {"devices": []}

    monkeypatch.setattr("ios_wifi_loc.session.discover", empty_discover)
    again = refresh_devices(store, "pymobiledevice3", timeout=1)
    assert again.details["added_count"] == 0
    assert again.details["known_count"] == 2
    assert "没有发现新设备" in again.summary
    assert {item["udid"] for item in store.load()["discovery"]} == {UDID_A, UDID_B}


def test_payload_backfills_selected_into_known_devices(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["discovery"] = []
    data["selected"] = {
        "udid": UDID_A,
        "transport": "mobdev2",
        "host": HOST_A,
        "name": "iPhone17 PRO",
        "product_version": "27.2.1",
        "connection": "wifi",
    }
    store.save(data)
    monkeypatch.setattr("ios_wifi_loc.session.discover", lambda *args, **kwargs: {"devices": []})
    payload = Console(store, "pymobiledevice3", "secret", require_auth=False, restore=False).payload()
    device = next(item for item in payload["devices"] if item["udid"] == UDID_A)
    assert device["host"] == HOST_A
    assert device["name"] == "iPhone17 PRO"
    persisted = store.load()["discovery"]
    assert any(item.get("udid") == UDID_A for item in persisted)


def test_pairing_backfill_does_not_overwrite_selected_transport(tmp_path):
    from ios_wifi_loc.pairing import import_plist
    from ios_wifi_loc.session import select_device

    store = StateStore(tmp_path / "state")
    import_plist(tmp_path / "state", f"{UDID_A}.plist", b"<?xml version='1.0'?><plist version='1.0'><dict></dict></plist>")
    outcome = select_device(store, udid=UDID_A, transport="usbmux", host=None, name="iPhone17 PRO", allow_usb=True, usbmux_address=None)
    assert outcome.ok, outcome.summary
    payload = Console(store, "pymobiledevice3", "secret", require_auth=False, restore=False).payload()
    device = next(item for item in payload["devices"] if item["udid"] == UDID_A)
    assert device["transport"] == "usbmux"
    assert store.load()["selected"]["transport"] == "usbmux"
    assert store.load()["discovery"][0]["transport"] == "usbmux"
