from __future__ import annotations

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page

def test_version_is_0517():
    assert __version__ == "0.5.17"
    html = render_page("csrf", no_auth=True, platform="")
    assert "<title>WiFi 虚拟定位</title>" in html
    assert "WiFi 虚拟定位 · v0.5.17" in html
    assert "v0.5.16" not in html


def test_favorite_click_toasts_highlights_and_scrolls_without_auto_set():
    html = render_page("csrf", no_auth=True)
    assert 'id="favs"' in html
    assert ".fav-item.selected, .device-card.selected" in html
    assert "border-color:var(--blue); background:#e8f1ff" in html
    assert ".fav-item:hover, .device-card:hover" in html
    assert "function revealMap()" in html
    assert "function previewLocation(newLat, newLon, zoom, hint)" in html
    assert 'scrollIntoView({ behavior: "smooth", block: "start" })' in html
    assert 'window.scrollTo({ top: 0, behavior: "smooth" })' in html
    assert "已选中收藏「" in html
    assert "点击「设置定位」生效" in html
    assert "markFavoriteSelected(item)" in html
    assert "selectedFavoriteId" in html
    assert "moveTo(newLat, newLon, zoom)" in html
    paint = html[html.index("favs.forEach((item)") : html.index("const pairing = data.pairing")]
    assert "previewLocation(parseFloat(item.latitude), parseFloat(item.longitude), 15" in paint
    assert "setLocation(" not in paint
    assert 'row.classList.add("selected")' in paint


def test_search_and_parse_url_hint_to_set_location_and_scroll():
    html = render_page("csrf", no_auth=True)
    search = html[html.index("async function searchPlace()") : html.index("function readPlistFiles")]
    assert "已跳转到指定坐标，点击「设置定位」生效" in search
    assert "已定位地图到「" in search
    assert "previewLocation(" in search
    assert "clearFavoriteSelection()" in search
    assert "nominatim.openstreetmap.org" in search
    assert search.index("已跳转到指定坐标") < search.index("nominatim.openstreetmap.org")
    parse = html[html.index('$("parse-url").onclick') : html.index('$("search").onclick')]
    assert "已解析为 WGS-84 坐标，点击「设置定位」生效" in parse
    assert "previewLocation(" in parse
    assert "setLocation(" not in parse


def test_clickable_controls_have_hover_active_and_transition():
    html = render_page("csrf", no_auth=True)
    assert ".btn-primary:hover:not(:disabled)" in html
    assert ".btn-secondary:hover:not(:disabled)" in html
    assert ".btn-danger:hover:not(:disabled)" in html
    assert ".layer-btn:hover:not(.active)" in html
    assert ".menu-select-toggle:hover, .menu-select-toggle:focus-visible" in html
    assert ".menu-option:hover, .menu-option:focus" in html
    assert ".presets button:hover, .presets button:focus-visible" in html
    assert ".fav-del:hover" in html
    assert ".drop:hover" in html
    assert "details summary:hover" in html
    group = ".btn, .presets button, .layer-btn, .copy-btn, .fav-del, .fav-item, .menu-select-toggle, .menu-option, .drop, details summary"
    assert group in html
    assert "scale(0.97)" in html
    assert ".fav-item:active, .menu-select-toggle:active, .menu-option:active" in html or ".fav-item:active" in html
    assert "background .15s ease" in html
