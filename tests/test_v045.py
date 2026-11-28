from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page
from ios_wifi_loc.windows_pair import render_windows_pair_bat


def test_version_is_045():
    assert __version__ == "0.5.20"
    html = render_page("csrf", no_auth=True)
    assert "v0.5.20" in html
    assert "v0.4.4" not in html


def test_rendered_html_has_no_broken_windows_pair_fragment():
    html = render_page("csrf", no_auth=True)
    assert html.count('id="download-windows-pair"') == 1
    assert 'class="btn btn-primary" id="download-windows-pair"' in html
    assert html.count("下载 Windows 一键配对工具 (.bat)") == 1
    # Leftover mid-attribute text from a broken tag must not leak into the page.
    assert 'condary" id="download-windows-pair"' not in html
    assert "btn-secondary\" id=\"download-windows-pair\"" not in html
    # After the pairing card's collapsed details, only the footer should follow — no raw attribute crumbs.
    after_pairing = html[html.rindex("</details>"):]
    assert 'id="download-windows-pair"' not in after_pairing
    assert "windows-pair.bat" not in after_pairing
    assert 'condary" id="download-windows-pair"' not in html
    assert after_pairing.count("下载 Windows 一键配对工具") == 0


def test_desktop_page_is_narrow_and_centered():
    html = render_page("csrf", no_auth=True)
    assert "max-width:720px" in html
    assert ".panel" in html
    assert "#login-card" in html
    assert "margin:0 auto" in html
    # The map is full-bleed; only the card column stays 720px.
    assert "#app { width:100%; max-width:none;" in html
    assert ".map-wrap { width:100%; max-width:100%;" in html
    assert "border-radius:0" in html
    assert "@media (max-width:600px)" in html
    assert "@media (min-width:601px) and (max-width:1024px)" not in html
    assert "@media (min-width:1025px)" in html
    assert "max-width:760px" not in html
    assert "max-width:820px" not in html
    assert "max-width:960px" not in html


def test_selected_device_card_is_three_rows():
    html = render_page("csrf", no_auth=True)
    assert "device-info-head" in html
    assert ".device-info-head { display:flex; justify-content:space-between; align-items:center;" in html
    assert 'id="device-info-title"' in html
    assert 'id="device-info-picked"' in html
    assert ">未连接</span>" in html
    assert "已连接" in html
    assert "badge-connected" in html
    assert "badge-disconnected" in html
    assert 'id="device-info-udid"' in html
    assert 'id="device-status"' in html
    assert (
        html.index('id="device-info-title"')
        < html.index('id="device-info-picked"')
        < html.index('id="device-info-udid"')
        < html.index('id="device-status"')
    )
    assert "device-info-pills" not in html
    assert "device-info-main" not in html


def test_status_card_and_extra_copy_are_gone():
    html = render_page("csrf", no_auth=True)
    assert "当前模拟状态" not in html
    assert 'id="command-line"' not in html
    assert 'id="phone-line"' not in html
    assert 'id="summary"' not in html
    assert 'id="tunneld-line"' not in html
    assert 'id="status"' not in html
    assert "未能确认。进程还在不能代表手机坐标" not in html
    assert "仅供受信局域网使用" not in html
    assert "请勿把 19443 端口暴露到公网" not in html
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位" in html and "v0.5.20" in html
    assert "OpenWrt 无线虚拟定位" not in html
    assert 'id="action-error"' in html
    for ident in ("command-line", "phone-line", "tunneld-line", "summary"):
        assert f'$("{ident}")' not in html
        assert f"$('{ident}')" not in html
    assert '$("status")' not in html
    assert "$('status')" not in html


def test_manual_pair_commands_are_short_while_bat_stays_automated():
    html = render_page("csrf", no_auth=True)
    script = render_windows_pair_bat("http://10.16.1.2:19443")
    cmd1 = html[html.index('id="pair-cmd-1"'):html.index("</pre>", html.index('id="pair-cmd-1"'))]
    cmd2 = html[html.index('id="pair-cmd-2"'):html.index("</pre>", html.index('id="pair-cmd-2"'))]
    assert "python -m pip install pymobiledevice3==11.63.1" in cmd1
    assert "pymobiledevice3 lockdown pair" in cmd1
    assert "pymobiledevice3 amfi enable-developer-mode" in cmd1
    assert "pymobiledevice3 lockdown pair" in cmd2
    assert "pymobiledevice3 lockdown wifi-connections on" in cmd2
    assert "Invoke-RestMethod" not in cmd1 and "Invoke-RestMethod" not in cmd2
    assert "winget" not in cmd1 and "winget" not in cmd2
    assert "WindowsApps" not in html
    assert "选择 .plist 文件" in html
    assert 'id="drop"' in html
    assert "展开手动配置与手动上传 (.plist)" in html
    assert "WindowsApps" in script
    assert "winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements" in script
    assert "Invoke-RestMethod" in script
    assert "/api/pairing/import" in script
    assert "SystemConfiguration.plist" in script
    assert "Refresh-Path" in script
    assert "-m pymobiledevice3" in script
