from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.service import (
    DEFAULT_SHORTCUT_CLEAR_ICLOUD_URL,
    DEFAULT_SHORTCUT_SET_ICLOUD_URL,
    Console,
    shortcut_settings,
)
from ios_wifi_loc.session import apply_device_metadata, remember_device_metadata
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page
from ios_wifi_loc.windows_pair import render_windows_pair_bat


SET_URL = "https://www.icloud.com/shortcuts/cf3227b48a8f484283069a087727f861"
CLEAR_URL = "https://www.icloud.com/shortcuts/395385a36be94384a85480d7459d1fa1"


def test_version_is_044():
    assert __version__ == "0.4.11"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.11" in html
    assert "v0.4.3" not in html


def test_default_shortcut_icloud_urls(monkeypatch):
    monkeypatch.delenv("IOS_WIFI_LOC_SHORTCUT_SET_URL", raising=False)
    monkeypatch.delenv("IOS_WIFI_LOC_SHORTCUT_CLEAR_URL", raising=False)
    assert DEFAULT_SHORTCUT_SET_ICLOUD_URL == SET_URL
    assert DEFAULT_SHORTCUT_CLEAR_ICLOUD_URL == CLEAR_URL
    links = shortcut_settings({})
    assert links["set_icloud_url"] == SET_URL
    assert links["clear_icloud_url"] == CLEAR_URL
    assert links["set_from_env"] is False
    assert links["clear_from_env"] is False

    stored = shortcut_settings({
        "settings": {
            "shortcuts": {
                "set_icloud_url": "https://www.icloud.com/shortcuts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "clear_icloud_url": "https://www.icloud.com/shortcuts/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        }
    })
    assert stored["set_icloud_url"].endswith("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert stored["clear_icloud_url"].endswith("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    empty = shortcut_settings({"settings": {"shortcuts": {"set_icloud_url": "", "clear_icloud_url": ""}}})
    assert empty["set_icloud_url"] == SET_URL
    assert empty["clear_icloud_url"] == CLEAR_URL

    monkeypatch.setenv("IOS_WIFI_LOC_SHORTCUT_SET_URL", "https://www.icloud.com/shortcuts/cccccccccccccccccccccccccccccccc")
    monkeypatch.setenv("IOS_WIFI_LOC_SHORTCUT_CLEAR_URL", "https://www.icloud.com/shortcuts/dddddddddddddddddddddddddddddddd")
    env_links = shortcut_settings({
        "settings": {
            "shortcuts": {
                "set_icloud_url": "https://www.icloud.com/shortcuts/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "clear_icloud_url": "https://www.icloud.com/shortcuts/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        }
    })
    assert env_links["set_icloud_url"].endswith("cccccccccccccccccccccccccccccccc")
    assert env_links["clear_icloud_url"].endswith("dddddddddddddddddddddddddddddddd")
    assert env_links["set_from_env"] is True
    assert env_links["clear_from_env"] is True


def test_shortcut_card_is_simple_install_buttons():
    html = render_page("csrf", no_auth=True)
    assert SET_URL in html
    assert CLEAR_URL in html
    assert "一键安装：地图分享定位" in html
    assert "一键安装：恢复真实定位" in html
    assert "安装后如本机地址不是默认地址" in html
    assert 'id="shortcut-set-icloud"' not in html
    assert 'id="shortcut-clear-icloud"' not in html
    assert "save-shortcut-set-icloud" not in html
    assert "save-shortcut-clear-icloud" not in html
    assert "shortcut-config-json" not in html
    assert "复制配置 JSON" not in html
    assert 'id="shortcut-set-url"' not in html
    assert 'id="shortcut-clear-url"' not in html
    assert 'id="shortcut-status-url"' not in html
    assert "shortcut-presets" not in html
    assert "获取 URL 内容" not in html
    assert "function fillShortcutUrls" not in html
    assert "function bindCopy" not in html
    assert "saveShortcutLinks" not in html
    assert "function copyText(text)" in html
    # Keep the pairing Windows tool download and the APIs themselves in the product,
    # but the simplified card no longer prints raw API URLs.
    assert "下载 Windows 一键配对工具 (.bat)" in html
    assert html.index("一键安装：地图分享定位") < html.index("一键安装：恢复真实定位")


def test_pairing_delete_button_matches_favorite_style():
    html = render_page("csrf", no_auth=True)
    assert ".fav-del {" in html
    assert ".fav-del:hover" in html
    assert "#dc2626" in html
    assert "border-radius:50%" in html or "border-radius: 50%" in html
    assert ".pair-file .fav-del" not in html
    # The old gray default on pairing rows is gone; both lists share .fav-del.
    start = html.index(".fav-del {")
    end = html.index("}", start)
    rule = html[start:end]
    assert "#dc2626" in rule
    assert "#f2f2f7" in rule
    assert "50%" in rule
    assert "#8e8e93" not in rule


def test_windows_pair_detects_and_installs_python():
    html = render_page("csrf", no_auth=True)
    script = render_windows_pair_bat("http://10.16.1.2:19443")
    # The webpage manual steps stay short; the one-click .bat keeps the full automations.
    assert "python -m pip install pymobiledevice3==11.63.1" in html
    assert "pymobiledevice3 lockdown pair" in html
    assert "pymobiledevice3 amfi enable-developer-mode" in html
    assert "pymobiledevice3 lockdown wifi-connections on" in html
    assert "WindowsApps" not in html
    assert "winget install" not in html
    assert "Invoke-RestMethod" not in html
    assert "Get-IosWifiPython" not in html
    assert "function fillPairCommands()" not in html
    assert "WindowsApps" in script
    assert "winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements" in script
    assert "GetEnvironmentVariable('Path','Machine')" in script
    assert "-m pymobiledevice3 lockdown pair" in script
    assert "-m pymobiledevice3 amfi enable-developer-mode" in script
    assert "pymobiledevice3==11.63.1" in script
    assert "@('python'" in script or "@('python', 'py')" in script or "@('python','py')" in script
    assert "Refresh-Path" in script
    assert r"C:\ProgramData\Apple\Lockdown" in script or "C:\\ProgramData\\Apple\\Lockdown" in script
    assert "/api/pairing/import" in script
    assert "SystemConfiguration.plist" in html and "SystemConfiguration.plist" in script
    assert "Invoke-RestMethod" in script
    assert "content_base64" in script
    assert "LastWriteTime" in script
    # After a successful winget install the bat continues instead of forcing a rerun.
    install_idx = script.index("winget install -e --id Python.Python.3.12")
    continue_idx = script.index("Refresh-Path", install_idx)
    rerun_exit = script.find("请先安装：", install_idx)
    assert continue_idx > install_idx
    assert rerun_exit == -1 or rerun_exit < install_idx


def test_pairing_card_promotes_windows_tool_and_folds_manual_steps():
    html = render_page("csrf", no_auth=True)
    body = html[html.index("<body>"):]
    assert 'class="btn btn-primary" id="download-windows-pair"' in html
    assert "下载 Windows 一键配对工具 (.bat)" in html
    assert "双击运行即可自动检测/安装 Python" in html
    assert "自动上传 2 个" in html
    assert "展开手动配置与手动上传 (.plist)" in html
    assert '<details class="pair-manual">' in html
    assert '<details class="pair-manual" open' not in html
    assert "上传" in html and "C:\\ProgramData\\Apple\\Lockdown\\" in html
    assert 'id="import-plist"' in html
    assert 'id="drop"' in html
    assert 'id="pair-cmd-1"' in html
    assert 'id="pair-cmd-2"' in html
    # Visible primary path comes first; manual steps stay inside the collapsed panel.
    assert body.index('id="pair-files"') < body.index('id="download-windows-pair"') < body.index("pair-manual")
    assert body.index("展开手动配置与手动上传") < body.index('id="pair-cmd-1"') < body.index('id="drop"') < body.index('id="import-plist"')
    assert 'class="btn btn-secondary" id="import-plist"' in html
    assert 'id="pair-auth-note"' in html
    assert "NO_AUTH ? \"none\"" in html or "NO_AUTH ? 'none'" in html


UDID = "0123456789abcdef0123456789abcdef01234567"


def test_device_metadata_is_not_downgraded_to_generic_iphone():
    data = {"device_names": {UDID: {"name": "iPhone17 PRO", "product_version": "27.2.1"}}}
    remember_device_metadata(data, {"udid": UDID, "name": "iPhone", "product_version": None})
    assert data["device_names"][UDID]["name"] == "iPhone17 PRO"
    assert data["device_names"][UDID]["product_version"] == "27.2.1"
    filled = apply_device_metadata({"udid": UDID, "name": None, "product_version": None, "connection": "wifi"}, data["device_names"])
    assert filled["name"] == "iPhone17 PRO"
    assert filled["product_version"] == "27.2.1"
    remember_device_metadata(data, {"udid": UDID, "name": "Lindon iPhone", "product_version": "27.2.1"})
    assert data["device_names"][UDID]["name"] == "Lindon iPhone"


def test_payload_backfills_discovery_name_and_version(tmp_path):
    store = StateStore(tmp_path / "state")
    data = store.load()
    data["discovery"] = [{
        "udid": UDID,
        "name": None,
        "product_version": None,
        "connection": "wifi",
        "transport": "mobdev2",
        "source": "tunneld",
        "host": "fe80::1%br-lan",
        "tunnel_ready": True,
    }]
    data["device_names"] = {UDID: {"name": "iPhone17 PRO", "product_version": "27.2.1"}}
    data["selected"] = {"udid": UDID, "transport": "mobdev2", "name": None, "product_version": None}
    store.save(data)
    payload = Console(store, "pymobiledevice3", "secret", require_auth=False, restore=False).payload()
    device = next(item for item in payload["devices"] if item["udid"] == UDID)
    assert device["name"] == "iPhone17 PRO"
    assert device["product_version"] == "27.2.1"
    assert payload["selected"]["name"] == "iPhone17 PRO"
    assert payload["selected"]["product_version"] == "27.2.1"


def test_device_dropdown_and_card_show_name_and_ios_version():
    html = render_page("csrf", no_auth=True)
    assert "function deviceTitle(item)" in html
    assert "function deviceCardTitle(item)" in html
    assert "function deviceName(item)" in html
    assert "function isGenericDeviceName(name)" in html
    assert "opt.textContent = deviceTitle(item);" in html
    assert "deviceCardTitle(current)" in html
    assert '" (iOS "' in html
    assert '" · iOS "' in html
    assert "lastPayload.device_names" in html
    assert "name: deviceName(item)" in html
    assert "overflow-wrap:anywhere" in html
    assert "word-break:break-all" in html
    assert "@media (max-width:420px)" in html
    assert "@media (max-width:600px)" in html
    assert "max-width:720px" in html
    assert "@media (min-width:601px) and (max-width:1024px)" not in html
    assert "@media (min-width:1025px)" not in html
    assert "min-height:44px" in html
    assert "flex-shrink:0" in html
