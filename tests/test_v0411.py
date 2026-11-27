from __future__ import annotations

from pathlib import Path

from ios_wifi_loc import __version__
from ios_wifi_loc.platform_label import detect_platform_label
from ios_wifi_loc.web_page import APP_TITLE, footer_brand, render_page


def _release(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_version_is_0411():
    assert __version__ == "0.5.15"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.15" in html
    assert "OpenWrt 无线虚拟定位" not in html
    assert "v0.4.10" not in html


def test_detect_platform_label_openwrt_ubuntu_debian(tmp_path):
    openwrt = _release(tmp_path, "openwrt", 'NAME="OpenWrt"\nVERSION="24.10.0"\nID=openwrt\n')
    assert detect_platform_label(openwrt) == "OpenWrt"
    ubuntu = _release(
        tmp_path,
        "ubuntu",
        'NAME="Ubuntu"\nVERSION="24.04.1 LTS (Noble Numbat)"\nID=ubuntu\nID_LIKE=debian\n',
    )
    assert detect_platform_label(ubuntu) == "Ubuntu"
    debian = _release(tmp_path, "debian", 'NAME="Debian GNU/Linux"\nID=debian\nVERSION_ID="12"\n')
    assert detect_platform_label(debian) == "Debian"


def test_detect_platform_label_alpine_other_and_macos(tmp_path):
    alpine = _release(tmp_path, "alpine", 'NAME="Alpine Linux"\nID=alpine\nVERSION_ID="3.20.0"\n')
    assert detect_platform_label(alpine) == "Alpine"
    fedora = _release(tmp_path, "fedora", 'NAME="Fedora Linux"\nID=fedora\nVERSION_ID="41"\n')
    assert detect_platform_label(fedora) == "Fedora"
    assert detect_platform_label(tmp_path / "missing", system="darwin") == "macOS"


def test_detect_platform_label_missing_or_unknown(tmp_path):
    assert detect_platform_label(tmp_path / "missing", system="linux") == ""
    empty = _release(tmp_path, "empty", "\n# just a comment\n")
    assert detect_platform_label(empty, system="linux") == ""


def test_footer_and_title_include_detected_platform(tmp_path):
    assert APP_TITLE == "WiFi 虚拟定位"
    openwrt = _release(tmp_path, "openwrt", "NAME=OpenWrt\nID=openwrt\n")
    html = render_page("csrf", no_auth=True, os_release_path=openwrt)
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · OpenWrt · v0.5.15" in html

    ubuntu = _release(tmp_path, "ubuntu", 'NAME="Ubuntu"\nID=ubuntu\n')
    html = render_page("csrf", no_auth=True, os_release_path=ubuntu)
    assert "WiFi 虚拟定位 · Ubuntu · v0.5.15" in html

    html = render_page("csrf", no_auth=True, platform="")
    assert "WiFi 虚拟定位 · v0.5.15" in html
    assert "WiFi 虚拟定位 ·  · v0.5.15" not in html
    assert footer_brand(platform="Debian") == "WiFi 虚拟定位 · Debian · v0.5.15"
    assert footer_brand(platform="") == "WiFi 虚拟定位 · v0.5.15"
