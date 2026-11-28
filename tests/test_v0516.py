from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page


def test_version_is_0516():
    assert __version__ == "0.5.20"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.20" in html
    assert "v0.5.15" not in html


def test_preset_city_buttons_are_large_enough_to_tap():
    html = render_page("csrf", no_auth=True)
    assert 'id="presets"' in html
    assert "东京" in html and "纽约" in html and "洛杉矶" in html
    assert "伦敦" in html and "新加坡" in html and "香港" in html
    assert "台北" in html and "首尔" in html
    # Larger than the previous 12px / 6px-padding chips.
    assert "padding:6px 10px; font-size:12px" not in html
    assert ".presets { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:8px;" in html
    assert ".presets button" in html
    assert "font-size:13.5px" in html[html.index(".presets button") : html.index(".presets button") + 280]
    assert "min-height:36px" in html[html.index(".presets button") : html.index(".presets button") + 280]
    assert "border-radius:10px" in html[html.index(".presets button") : html.index(".presets button") + 280]
    media = html[html.index("@media (max-width:1024px)") : html.index("@media (max-width:600px)")]
    assert "font-size:14px" in media
    assert "min-height:40px" in media
    assert "padding:8px 8px" in media
    assert ".presets { gap:10px; }" in media
    assert ".fav-item { min-height:44px;" in media
    assert ".presets button:hover, .presets button:focus-visible" in html
    assert ".presets button.is-selected" in html
    assert 'item.classList.toggle("is-selected", item === btn)' in html
