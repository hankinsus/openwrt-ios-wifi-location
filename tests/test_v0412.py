from __future__ import annotations

from pathlib import Path

from ios_wifi_loc import __version__
from ios_wifi_loc.platform_label import detect_platform_label
from ios_wifi_loc.web_page import footer_brand, render_page
from ios_wifi_loc.windows_pair import PS_MARKER, encode_windows_pair_bat, extract_embedded_ps_body, render_windows_pair_bat


def test_version_is_0412():
    assert __version__ == "0.5.16"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.16" in html
    assert "v0.4.11" not in html


def test_windows_pair_bat_ascii_header_crlf_and_uploads_all_plists():
    script = render_windows_pair_bat("http://10.16.1.2:19443")
    sep = "\r\n" + PS_MARKER + "\r\n"
    assert sep in script
    header = script.rsplit(sep, 1)[0]
    body = extract_embedded_ps_body(script)
    header.encode("ascii")
    assert "\r\n" in header and script.startswith("@echo off\r\n")
    assert "^" not in header
    assert "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand" in header
    assert " -Command " not in header
    assert PS_MARKER not in header
    assert body.strip()
    assert "WindowsApps" in body
    assert "winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements" in body
    assert "Refresh-Path" in body
    assert "-m pymobiledevice3 lockdown pair" in body
    assert "-m pymobiledevice3 amfi enable-developer-mode" in body
    assert "pymobiledevice3==11.63.1" in body
    assert r"C:\ProgramData\Apple\Lockdown" in body
    assert "/api/pairing/import" in body
    assert "SystemConfiguration.plist" in body
    assert "Invoke-RestMethod" in body
    assert "content_base64" in body
    assert "Get-ChildItem -LiteralPath $dir -Filter '*.plist' -File" in body
    assert "LastWriteTime" not in script
    assert "Select-Object -First 1" not in script
    raw = encode_windows_pair_bat(script)
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\r\n") >= 10
    assert b"\n" == b"\n"  # keep flake quiet
    # No bare LF line endings in the served bytes (CRLF only).
    assert b"\n" in raw and raw.replace(b"\r\n", b"").find(b"\n") == -1


def test_none_os_release_path_uses_default_and_openwrt_fallback(tmp_path, monkeypatch):
    missing = tmp_path / "missing-os-release"
    openwrt = tmp_path / "openwrt_release"
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="OpenWrt"\nID=openwrt\n', encoding="utf-8")
    monkeypatch.setattr("ios_wifi_loc.platform_label.DEFAULT_OS_RELEASE", os_release)
    monkeypatch.setattr("ios_wifi_loc.platform_label.DEFAULT_OPENWRT_RELEASE", missing)
    assert detect_platform_label(None) == "OpenWrt"
    assert detect_platform_label() == "OpenWrt"
    assert footer_brand() == "WiFi 虚拟定位 · OpenWrt · v0.5.16"

    os_release.unlink()
    openwrt.write_text("DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='24.10.0'\n", encoding="utf-8")
    monkeypatch.setattr("ios_wifi_loc.platform_label.DEFAULT_OS_RELEASE", missing)
    monkeypatch.setattr("ios_wifi_loc.platform_label.DEFAULT_OPENWRT_RELEASE", openwrt)
    assert detect_platform_label(None, system="linux") == "OpenWrt"
    assert footer_brand() == "WiFi 虚拟定位 · OpenWrt · v0.5.16"


def test_footer_is_full_width_centered_outside_panel():
    html = render_page("csrf", no_auth=True, platform="")
    assert ".footer-card { width:100%; max-width:none; margin:36px 0 24px; padding:8px 16px; text-align:center;" in html
    assert ".footer-brand { font-weight:600; font-size:15px; color:var(--text); margin-bottom:0; text-align:center; width:100%; }" in html
    chunk = html[html.index('<div id="app"'):html.index('<div class="toast"')]
    footer_at = chunk.index('<div class="footer-card">')
    panel_at = chunk.rfind('<div class="panel"', 0, footer_at)
    assert panel_at != -1
    fragment = chunk[panel_at:footer_at]
    assert fragment.count("<div") == fragment.count("</div>")
    assert chunk[footer_at:].strip().endswith("</div>")
    # Footer must come after the main panel (pairing card lives there).
    assert 'id="download-windows-pair"' in chunk[:footer_at]
