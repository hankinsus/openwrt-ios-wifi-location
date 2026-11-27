from __future__ import annotations

import base64
import json
import os
import signal
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UDID = "0123456789abcdef0123456789abcdef01234567"
OTHER = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
IPHONE = "00008150-0015543914F0C01C"


def test_resolve_binary_prefers_venv_sibling(tmp_path, monkeypatch):
    from ios_wifi_loc.binary import resolve_binary

    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python3"
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    sibling = venv_bin / "pymobiledevice3"
    sibling.write_text("#!/bin/sh\n", encoding="utf-8")
    sibling.chmod(0o755)
    monkeypatch.setattr("ios_wifi_loc.binary.shutil.which", lambda name: "/usr/bin/pymobiledevice3")
    assert resolve_binary("pymobiledevice3", python_executable=str(python)) == str(sibling)
    assert resolve_binary("/explicit/pymobiledevice3") == "/explicit/pymobiledevice3"


def test_bonjour_json_and_tunneld_merge(tunneld_stub, monkeypatch):
    from ios_wifi_loc.discovery import merge_devices, parse_device_records
    from ios_wifi_loc.tunneld import parse_tunneld_payload, query_tunneld

    raw = json.dumps(
        [
            {
                "UniqueDeviceID": IPHONE,
                "DeviceName": "iPhone 17 Pro",
                "ProductVersion": "27.2.1",
                "ProductType": "iPhone18,2",
                "ip": "fe80::1093:44ea:c869:5bd7%br-lan",
            }
        ]
    )
    devices = parse_device_records(raw, source="bonjour_mobdev2", connection="wifi", transport="mobdev2")
    assert devices[0]["udid"] == IPHONE
    assert devices[0]["name"] == "iPhone 17 Pro"
    assert devices[0]["product_version"] == "27.2.1"
    assert devices[0]["host"] == "fe80::1093:44ea:c869:5bd7%br-lan"

    payload = {IPHONE: [{"tunnel-address": "fd53:9fd:3f::1", "tunnel-port": 52679, "interface": "fe80::1%br-lan"}]}
    tunnels = parse_tunneld_payload(payload)
    assert tunnels[0]["udid"] == IPHONE
    assert tunnels[0]["port"] == 52679

    monkeypatch.setenv("IOS_WIFI_LOC_TUNNELD_URL", tunneld_stub)
    # default stub body is {}
    status = query_tunneld()
    assert status["reachable"] is True

    merged = merge_devices(
        devices,
        [{"udid": IPHONE, "connection": "wifi", "transport": "mobdev2", "source": "tunneld", "tunnel_ready": True, "host": "fd53:9fd:3f::1", "name": None, "product_version": None, "product_type": None}],
    )
    assert len(merged) == 1
    assert merged[0]["tunnel_ready"] is True
    assert merged[0]["name"] == "iPhone 17 Pro"


def test_ipv6_zone_host_validation():
    from ios_wifi_loc.identifiers import IdentifierError, validate_host

    assert validate_host("fe80::1093:44ea:c869:5bd7%br-lan") == "fe80::1093:44ea:c869:5bd7%br-lan"
    assert validate_host("fd53:9fd:3f::1") == "fd53:9fd:3f::1"
    assert validate_host("192.0.2.10") == "192.0.2.10"
    with pytest.raises(IdentifierError):
        validate_host("fe80::1%bad;rm")
    with pytest.raises(IdentifierError):
        validate_host("not a host")


def test_tunnel_argv_for_ios17_wireless():
    from ios_wifi_loc.upstream import Target, location_argv

    target = Target(IPHONE, "mobdev2")
    argv = location_argv("pymobiledevice3", target, "set", "ios17", "35.6812", "139.7671", use_tunnel=True)
    assert argv[1:6] == ["developer", "dvt", "simulate-location", "set", "--tunnel"]
    assert argv[argv.index("--tunnel") + 1] == IPHONE
    assert "--udid" not in argv and "--mobdev2" not in argv
    clear = location_argv("pymobiledevice3", target, "clear", "ios17", use_tunnel=True)
    assert "--tunnel" in clear and IPHONE in clear
    # default remains the documented non-tunnel flags for unit-level callers
    legacy = location_argv("pymobiledevice3", target, "clear", "ios17")
    assert "--mobdev2" in legacy and "--tunnel" not in legacy


def test_pairing_import_rejects_traversal_and_hides_contents(tmp_path):
    from ios_wifi_loc.pairing import PairingError, delete_plist, import_plist, list_pairing

    state = tmp_path / "state"
    runtime = tmp_path / "var" / "lib" / "lockdown"
    xml = b'<?xml version="1.0"?><plist><dict><key>HostPrivateKey</key><data>SECRETKEYMATERIAL</data></dict></plist>'
    report = import_plist(state, f"{IPHONE}.plist", xml, runtime_dir=runtime)
    assert report["imported"] == f"{IPHONE}.plist"
    assert report["count"] == 1
    listed = list_pairing(state, runtime_dir=runtime)
    blob = json.dumps(listed)
    assert "SECRETKEYMATERIAL" not in blob
    assert listed["files"][0]["udid"] == IPHONE
    assert oct((state / "lockdown" / f"{IPHONE}.plist").stat().st_mode & 0o777) == "0o600"
    assert (runtime / f"{IPHONE}.plist").is_file()
    with pytest.raises(PairingError):
        import_plist(state, "../etc/passwd.plist", xml, runtime_dir=runtime)
    with pytest.raises(PairingError):
        import_plist(state, "foo/bar.plist", xml, runtime_dir=runtime)
    with pytest.raises(PairingError):
        import_plist(state, "notes.txt", xml, runtime_dir=runtime)
    with pytest.raises(PairingError):
        import_plist(state, "ok.plist", b"not a plist", runtime_dir=runtime)
    deleted = delete_plist(state, f"{IPHONE}.plist", runtime_dir=runtime)
    assert deleted["count"] == 0
    assert not (state / "lockdown" / f"{IPHONE}.plist").exists()


def test_install_openwrt_init_has_tunneld_and_persistent_state(tmp_path):
    from ios_wifi_loc.install import default_state_dir_for_root, install_files, migrate_openwrt_state

    root = tmp_path / "openwrt"
    (root / "etc").mkdir(parents=True)
    (root / "etc/openwrt_release").write_text("DISTRIB_ID='OpenWrt'\n", encoding="utf-8")
    assert default_state_dir_for_root(root) == root / "etc/ios-wifi-loc"

    old = root / "var/lib/ios-wifi-loc"
    old.mkdir(parents=True)
    (old / "web.secret").write_text("existing-secret-value-32chars-ok\n", encoding="utf-8")
    (old / "state.json").write_text('{"version":1,"favorites":[]}\n', encoding="utf-8")
    runtime = root / "var/lib/lockdown"
    runtime.mkdir(parents=True)
    (runtime / f"{IPHONE}.plist").write_text("<plist></plist>", encoding="utf-8")

    state = root / "etc/ios-wifi-loc"
    notes = migrate_openwrt_state(root, state)
    assert any("web.secret" in item for item in notes)
    assert (state / "web.secret").read_text(encoding="utf-8").strip() == "existing-secret-value-32chars-ok"

    python = tmp_path / "venv" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    installed = install_files(
        root,
        state_dir=state,
        executable=str(python),
        interface="br-lan",
        binary=str(python.parent / "pymobiledevice3"),
    )
    script = Path(installed["unit"]).read_text(encoding="utf-8")
    assert installed["init"] == "procd"
    assert "procd_open_instance tunneld" in script
    assert "remote tunneld --protocol tcp --no-usb --no-usbmux --mobdev2" in script
    assert "procd_set_param respawn" in script
    assert "/etc/ios-wifi-loc" in script
    assert "sync_lockdown" in script
    assert "/var/lib/lockdown" in script
    assert "--no-auth" in script
    assert "--require-auth" not in script
    assert "--binary" in script
    assert "--interface br-lan" in script
    assert "0.0.0.0" not in script
    # existing secret was not rotated
    assert (state / "web.secret").read_text(encoding="utf-8").strip() == "existing-secret-value-32chars-ok"
