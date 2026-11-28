from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page


def test_version_is_0519():
    assert __version__ == "0.5.20"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.20" in html
    assert "v0.5.18" not in html


def test_shortcut_buttons_drop_one_click_install_prefix():
    html = render_page("csrf", no_auth=True)
    assert "一键安装：" not in html
    assert ">地图分享定位</a>" in html
    assert ">恢复真实定位</a>" in html
    assert "https://www.icloud.com/shortcuts/cf3227b48a8f484283069a087727f861" in html
    assert "https://www.icloud.com/shortcuts/395385a36be94384a85480d7459d1fa1" in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert html.index(">地图分享定位</a>") < html.index(">恢复真实定位</a>")
    # Explanatory copy still tells the user to install the shortcuts.
    assert "在 iPhone 上安装下面两个快捷指令后" in html


def test_desktop_card_column_is_narrower_than_tablet():
    html = render_page("csrf", no_auth=True)
    # Tablets keep the previous 720px cap; phones stay full-width.
    assert ".panel { padding:16px; max-width:720px;" in html
    assert "#login-card { max-width:720px;" in html
    desktop = html[html.index("@media (min-width:1025px)") : html.index("@media (max-width:420px)")]
    assert "#login-card { max-width:600px; padding:14px 16px; }" in desktop
    assert ".panel { max-width:600px; padding:14px 16px; }" in desktop
    assert ".card { padding:14px; margin-bottom:10px; }" in desktop
    assert ".shortcut-install .btn { flex:1 1 calc(50% - 8px); }" in desktop
    phone = html[html.index("@media (max-width:600px)") :]
    assert ".btn { min-height:44px; }" in phone
    assert "#map { height:420px;" in html
    assert ".footer-card { width:100%; max-width:none;" in html or ".footer-card { width:100%" in html
