from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page


def test_version_is_0518():
    assert __version__ == "0.5.19"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.19" in html
    assert "v0.5.17" not in html


def test_city_presets_preview_on_map_and_do_not_auto_set_location():
    html = render_page("csrf", no_auth=True)
    start = html.index("CITIES.forEach((city)")
    end = html.index("document.querySelectorAll(\".layer-btn\")", start)
    block = html[start:end]
    assert 'item.classList.toggle("is-selected", item === btn)' in block
    assert "clearFavoriteSelection()" in block
    assert "previewLocation(city.lat, city.lon, 14" in block
    assert "已选中城市「" in block
    assert "点击「设置定位」生效" in block
    assert "setLocation(" not in block
    assert "setLocation(true)" not in html[start:end]
    # The only remaining setLocation calls are the explicit 设置定位 button and helpers.
    assert '$("start").onclick = () => setLocation(false);' in html
