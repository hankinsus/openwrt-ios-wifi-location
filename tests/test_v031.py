from __future__ import annotations

from pathlib import Path

from ios_wifi_loc import __version__
from ios_wifi_loc.watchdog import backoff_series, log_contains_error
from ios_wifi_loc.web_page import render_page


def test_version_is_current():
    assert __version__ == "0.5.19"


def test_web_page_device_dropdown_pairing_guide_and_button_feedback():
    html = render_page("csrf-token", no_auth=True)
    assert 'id="device-select"' in html
    assert "高级 / 手动添加" in html
    assert "pymobiledevice3==11.63.1" in html
    assert "-m pip install" in html
    assert "pymobiledevice3 amfi enable-developer-mode" in html
    assert "pymobiledevice3 lockdown wifi-connections on" in html
    assert "选择 .plist 文件" in html
    assert "C:\\ProgramData\\Apple\\Lockdown\\" in html
    assert "/etc/ios-wifi-loc/lockdown" in html
    assert "scale(0.97)" in html
    assert "设置中..." in html
    assert "恢复中..." in html
    assert "检测中..." in html
    assert "添加设备检测" in html
    assert "重新扫描" not in html
    assert "✅ 已下发定位" in html
    assert "✅ 已恢复真实定位" in html
    assert "window.isSecureContext" in html
    assert "已回到当前保存位置" in html
    assert "已回到默认位置（东京）" in html
    assert "浏览器仅在 HTTPS 下允许获取本机 GPS" not in html
    assert "Only secure origins are allowed" not in html
    assert "保持中（自动重连已开启，已重连 " in html
    assert "等待隧道恢复自动重连…" in html
    assert "v0.5.19" in html
    assert "navigator.geolocation.getCurrentPosition" in html


def test_watchdog_backoff_and_error_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("IOS_WIFI_LOC_WATCHDOG_BACKOFF", "3,5,99")
    assert backoff_series() == [3.0, 5.0, 10.0]
    path = tmp_path / "stderr.log"
    path.write_bytes(b"hello\n")
    hit, excerpt, offset = log_contains_error(path, 0)
    assert hit is False
    path.write_bytes(b"hello\nDTX reader exiting with error: [Errno 101] Network unreachable\n")
    hit, excerpt, offset = log_contains_error(path, offset)
    assert hit is True
    assert "Network unreachable" in excerpt
    hit, excerpt, offset = log_contains_error(path, offset)
    assert hit is False
