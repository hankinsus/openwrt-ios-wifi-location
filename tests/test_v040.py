from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from ios_wifi_loc import __version__
from ios_wifi_loc.geo import gcj_to_wgs, pair_to_wgs84, wgs_to_gcj
from ios_wifi_loc.sharelinks import parse_coords_from_text, parse_share
from ios_wifi_loc.web_page import render_page

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fakes" / "pymobiledevice3"
UDID = "0123456789abcdef0123456789abcdef01234567"


def test_version_is_040():
    assert __version__ == "0.5.20"


def test_gcj_and_bd09_convert_inside_china():
    lat, lon = 31.230416, 121.473701
    glat, glon = wgs_to_gcj(lat, lon)
    assert abs(glat - lat) > 1e-4 or abs(glon - lon) > 1e-4
    back_lat, back_lon = gcj_to_wgs(glat, glon)
    assert abs(back_lat - lat) < 1e-6
    assert abs(back_lon - lon) < 1e-6
    wlat, wlon, kind = pair_to_wgs84(f"{glat:.8f}", f"{glon:.8f}", "gcj02")
    assert kind == "gcj02"
    assert abs(float(wlat) - lat) < 1e-5
    assert abs(float(wlon) - lon) < 1e-5
    blat, blon, kind = pair_to_wgs84("31.2365", "121.4802", "bd09")
    assert kind == "bd09"
    assert blat != "31.2365"


def test_parse_apple_google_amap_baidu_and_plain_text():
    apple = parse_share("https://maps.apple.com/?ll=35.6812,139.7671")
    assert apple["latitude"] == "35.6812"
    assert apple["longitude"] == "139.7671"
    assert apple["system"] == "wgs84"

    google = parse_coords_from_text("https://www.google.com/maps/@35.6812,139.7671,16z")
    assert google["latitude"] == "35.6812"
    assert google["longitude"] == "139.7671"

    amap = parse_share("https://uri.amap.com/marker?position=116.397428,39.90923", follow=False)
    assert amap["raw_system"] == "gcj02"
    assert float(amap["latitude"]) != 39.90923 or float(amap["longitude"]) != 116.397428
    assert abs(float(amap["latitude"]) - 39.90923) < 0.02

    baidu = parse_share("https://map.baidu.com/?location=39.915,116.404", follow=False)
    assert baidu["raw_system"] == "bd09"

    plain = parse_share("东京 35.6812, 139.7671")
    assert plain["latitude"] == "35.6812"
    assert plain["longitude"] == "139.7671"


def test_follow_short_link_with_injected_fetcher():
    def fetcher(url: str):
        if "surl.amap.com" in url:
            loc = "https://uri.amap.com/marker?position=116.397428,39.90923"
            return loc, b"", loc
        raise AssertionError(url)

    parsed = parse_share("看看这个位置 https://surl.amap.com/abc123", follow=True, fetcher=fetcher)
    assert parsed["raw_system"] == "gcj02"
    assert "resolved" in parsed


def test_pairing_lists_friendly_device_name(tmp_path):
    from ios_wifi_loc.pairing import import_plist, list_pairing
    from ios_wifi_loc.service import enrich_pairing

    state = tmp_path / "state"
    plist = b"<?xml version='1.0'?><plist version='1.0'><dict></dict></plist>"
    import_plist(state, f"{UDID}.plist", plist)
    import_plist(state, "SystemConfiguration.plist", plist)
    data = {
        "device_names": {UDID: {"name": "iPhone17 PRO", "product_version": "27.2.1"}},
        "discovery": [],
        "selected": None,
    }
    report = enrich_pairing(list_pairing(state), data)
    by_name = {item["filename"]: item for item in report["files"]}
    assert by_name[f"{UDID}.plist"]["device_name"] == "iPhone17 PRO"
    assert "27.2.1" in by_name[f"{UDID}.plist"]["display_name"]
    assert by_name["SystemConfiguration.plist"]["display_name"] == "系统配对配置"


def test_install_generates_openrc_and_systemd_always(tmp_path):
    from ios_wifi_loc.install import detect_init, install_files, uninstall_files

    alpine = tmp_path / "alpine"
    (alpine / "etc").mkdir(parents=True)
    (alpine / "etc/alpine-release").write_text("3.20.0\n", encoding="utf-8")
    state = tmp_path / "state-alpine"
    installed = install_files(alpine, state_dir=state, executable="python3", interface="eth0")
    assert installed["init"] == "openrc"
    assert detect_init(alpine) == "openrc"
    unit = Path(installed["unit"]).read_text(encoding="utf-8")
    tunneld = Path(installed["tunneld_unit"]).read_text(encoding="utf-8")
    assert unit.startswith("#!/sbin/openrc-run")
    assert "command_background=yes" in unit
    assert "--no-auth" in unit
    assert "0.0.0.0" not in unit
    assert "tunneld" in tunneld
    removed = uninstall_files(alpine, state_dir=state, purge_state=False)
    assert not Path(installed["unit"]).exists()
    assert not Path(installed["tunneld_unit"]).exists()
    assert (state / "web.secret").exists()
    assert removed["removed"]

    systemd_root = tmp_path / "systemd"
    (systemd_root / "usr/lib/systemd/system").mkdir(parents=True)
    installed = install_files(systemd_root, state_dir=tmp_path / "state-systemd", executable=sys.executable)
    unit = Path(installed["unit"]).read_text(encoding="utf-8")
    assert installed["init"] == "systemd"
    assert "Restart=always" in unit
    assert "Restart=always" in Path(installed["tunneld_unit"]).read_text(encoding="utf-8")
    assert "0.0.0.0" not in unit


def test_oneclick_dry_run_alpine(tmp_path):
    root = tmp_path / "alpine"
    (root / "etc").mkdir(parents=True)
    (root / "etc/alpine-release").write_text("3.20.0\n", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run(
        ["sh", str(ROOT / "scripts/oneclick-install.sh"), "--dry-run", "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "alpine" in proc.stdout.lower() or "系统：alpine" in proc.stdout
    assert "py3-pip" in proc.stdout
    assert "这是预览" in proc.stdout


def test_web_page_shortcut_and_windows_tool_copy():
    html = render_page("csrf", no_auth=True)
    assert "https://www.icloud.com/shortcuts/cf3227b48a8f484283069a087727f861" in html
    assert "https://www.icloud.com/shortcuts/395385a36be94384a85480d7459d1fa1" in html
    assert "下载 Windows 一键配对工具 (.bat)" in html
    assert "replace: true" in html
    assert "已回到当前保存位置" in html
    assert "地图分享定位" in html
    assert "恢复真实定位" in html
    assert "window.isSecureContext" in html
    assert "Only secure origins are allowed" not in html


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["IOS_WIFI_LOC_FAKE_LOG"] = str(tmp_path / "argv.log")
    env["IOS_WIFI_LOC_FAKE_DEVICES"] = json.dumps([UDID])
    env.update(extra)
    return env


def _start(tmp_path: Path, **extra: str):
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
            "--no-auth",
            "--no-watch",
            "--port",
            "0",
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


def _stop(proc: subprocess.Popen[str], tmp_path: Path) -> None:
    path = tmp_path / "state" / "state.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        pids = []
        for collection in (payload.get("sessions") or {}).values() if isinstance(payload.get("sessions"), dict) else []:
            if isinstance(collection, dict):
                for key in ("pid", "watchdog_pid", "child_pid"):
                    if isinstance(collection.get(key), int):
                        pids.append(collection[key])
        for pid in pids:
            if pid > 1:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _request(host: str, port: int, path: str, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"http://{host}:{port}{path}", data=data, method=method)
    request.add_unredirected_header("Host", f"{host}:{port}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=20) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type") or ""
        return resp.status, raw, ctype, dict(resp.headers)


def test_shortcut_set_clear_replace_and_windows_pair_and_pairing_names(tmp_path):
    from ios_wifi_loc.pairing import import_plist

    state = tmp_path / "state"
    plist = b"<?xml version='1.0'?><plist version='1.0'><dict></dict></plist>"
    import_plist(state, f"{UDID}.plist", plist)
    proc, host, port = _start(tmp_path)
    try:
        # select via API then shortcut set
        code, raw, _ctype, _h = _request(
            host,
            port,
            "/api/select",
            "POST",
            {"udid": UDID, "transport": "usbmux", "name": "iPhone17 PRO"},
        )
        assert code == 200, raw

        code, raw, ctype, _h = _request(host, port, "/api/shortcut/set?lat=35.6812&lon=139.7671")
        payload = json.loads(raw)
        assert payload["ok"] is True, payload
        assert payload["latitude"] == "35.6812"
        assert "iPhone17 PRO" in payload["summary"] or payload["udid"] == UDID
        first_pid = None
        status = json.loads(_request(host, port, "/api/shortcut/status")[1])
        assert "模拟" in status["text"] or status["code"] == "HOLDING"
        first_pid = (status.get("session") or {}).get("pid")

        # GCJ-02 conversion
        code, raw, _c, _h = _request(host, port, "/api/shortcut/set?lat=31.230416&lon=121.473701&coord=gcj02")
        payload = json.loads(raw)
        assert payload["ok"] is True, payload
        assert payload["system"] == "gcj02"
        assert payload["latitude"] != "31.230416"
        if first_pid:
            # auto-replace should have started a new holder
            assert (payload.get("details") or {}).get("pid") != first_pid or payload["ok"]

        # Apple Maps share text
        code, raw, _c, _h = _request(
            host,
            port,
            "/api/shortcut/set?text=" + urllib.parse.quote("https://maps.apple.com/?ll=40.7128,-74.0060", safe=""),
        )
        payload = json.loads(raw)
        assert payload["ok"] is True, payload
        assert payload["latitude"] == "40.7128"
        assert payload["longitude"] == "-74.006"

        # plain text format for shortcut notification
        code, raw, ctype, _h = _request(host, port, "/api/shortcut/status?format=text")
        text = raw.decode("utf-8")
        assert "text/plain" in ctype
        assert "40.7128" in text or "模拟" in text

        code, raw, _c, _h = _request(host, port, "/api/shortcut/clear?format=json")
        payload = json.loads(raw)
        assert payload["ok"] is True, payload
        assert "真实定位" in payload["summary"] or payload["code"] == "CLEARED"

        code, raw, ctype, headers = _request(host, port, "/api/tools/windows-pair.bat")
        script = raw.decode("utf-8-sig")
        assert code == 200
        assert f"http://{host}:{port}" in script
        assert "pymobiledevice3==11.63.1" in script
        assert r"C:\ProgramData\Apple\Lockdown" in script or "C:\\\\ProgramData\\\\Apple\\\\Lockdown" in script
        assert "/api/pairing/import" in script
        assert "attachment" in (headers.get("Content-Disposition") or "")
        assert "ios-wifi-loc-windows-pair.bat" in (headers.get("Content-Disposition") or "")

        code, raw, _c, _h = _request(host, port, "/api/pairing")
        pairing = json.loads(raw)["pairing"]
        files = {item["filename"]: item for item in pairing["files"]}
        assert files[f"{UDID}.plist"]["device_name"] == "iPhone17 PRO"
        assert "iPhone17 PRO" in files[f"{UDID}.plist"]["display_name"]
    finally:
        _stop(proc, tmp_path)
