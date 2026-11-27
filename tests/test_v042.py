from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page


def _order(*labels: str, html: str) -> None:
    positions = [html.index(label) for label in labels]
    assert positions == sorted(positions), list(zip(labels, positions))


def test_version_is_042():
    assert __version__ == "0.4.4"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.4" in html


def test_single_blue_device_card_and_manual_fallback_only():
    html = render_page("csrf", no_auth=True)
    assert 'id="device-info"' in html
    assert "border:1px solid var(--blue)" in html or "border:1px solid var(--blue)" in html.replace(" ", "")
    assert html.count('id="device-select"') == 1
    assert 'id="devices"' not in html
    assert "高级 / 手动添加" in html
    assert 'id="transport"' in html
    assert 'id="udid"' in html
    assert 'id="host"' in html
    assert "选择此设备" in html
    # Device list under advanced is gone; the selected card lives under the dropdown.
    assert html.index('id="device-select"') < html.index('id="device-info"') < html.index("高级 / 手动添加")
    assert "className = \"device-card\"" not in html
    assert "card.className = \"device-card\"" not in html


def test_copy_text_falls_back_on_insecure_http():
    html = render_page("csrf", no_auth=True)
    assert "function copyText(text)" in html
    assert "navigator.clipboard && window.isSecureContext" in html
    assert "document.execCommand('copy')" in html or 'document.execCommand("copy")' in html
    assert "setSelectionRange(0, 99999)" in html
    assert "textarea" in html
    assert 'setAttribute("readonly", "readonly")' in html or "setAttribute('readonly'" in html
    assert "toast(\"已复制\"" in html or "toast('已复制'" in html
    assert "复制失败，请手动选择命令" not in html
    # All copy buttons go through copyText, not a raw clipboard call.
    assert html.count("navigator.clipboard.writeText") == 1
    assert "await copyText(value)" in html


def test_location_card_order_coordinate_input_and_pairing_badge():
    html = render_page("csrf", no_auth=True)
    _order(
        'id="map"',
        'id="device-select"',
        "选择目标位置",
        "我的收藏",
        "搜索地点",
        "粘贴地图链接",
        "iOS 快捷指令",
        "配对管理",
        html=html,
    )
    assert "共享系统配置" not in html
    assert "pair-group" in html
