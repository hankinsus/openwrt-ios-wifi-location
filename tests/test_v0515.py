from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page


def test_version_is_0515():
    assert __version__ == "0.5.18"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.18" in html
    assert "v0.4.14" not in html
    assert "v0.4.15" not in html


def test_transport_row_and_pills_removed_manual_defaults_to_mobdev2():
    html = render_page("csrf", no_auth=True)
    assert 'id="device-info-transport"' not in html
    assert 'id="transport-pills"' not in html
    assert "function setTransport" not in html
    assert "mobdev2（无线）" not in html
    assert "usbmux 网络" not in html
    assert "传输类型" not in html
    assert ">传输<" not in html and "<label>传输" not in html
    assert "class=\"segment" not in html
    assert "标识（UDID）和主机仅在设备未被自动发现时需要手动填写。" in html
    assert "传输类型、主机和标识" not in html
    assert 'id="device-info-udid"' in html
    assert 'id="device-info-host"' in html
    assert 'fillMetaRow("device-info-udid", "UDID"' in html
    assert 'fillMetaRow("device-info-host", "IP"' in html
    assert 'fillMetaRow("device-info-transport"' not in html
    assert 'id="transport"' in html
    assert 'id="transport" value="mobdev2"' in html
    assert "<select" not in html
    # Manual "选择此设备" still posts transport, defaulting to mobdev2.
    assert 'id="choose"' in html
    assert "transport: ($(\"transport\") && $(\"transport\").value) || \"mobdev2\"" in html
    assert "$(\"udid\").value" in html
    assert "$(\"host\").value" in html
