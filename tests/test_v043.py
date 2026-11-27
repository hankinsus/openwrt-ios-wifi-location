from __future__ import annotations

import re

from ios_wifi_loc import __version__
from ios_wifi_loc.web_page import render_page


def _js_function(html: str, name: str) -> str:
    start = html.index(f"function {name}(")
    nxt = html.find("\nfunction ", start + 1)
    nxt2 = html.find("\nasync function ", start + 1)
    cuts = [i for i in (nxt, nxt2) if i != -1]
    end = min(cuts) if cuts else start + 2000
    return html[start:end]


def test_version_is_043():
    assert __version__ == "0.4.14"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.14" in html


def test_horizontal_device_card_layout():
    html = render_page("csrf", no_auth=True)
    assert "device-info-head" in html
    assert 'id="device-info-picked"' in html
    assert "flex-shrink:0" in html
    assert "badge-pick" in html
    assert ">未连接</span>" in html or "已连接" in html
    assert "justify-content:space-between" in html
    assert "align-items:center" in html
    assert "@media (max-width:420px)" in html
    assert html.index('id="device-select"') < html.index('id="device-info"') < html.index("高级 / 手动添加")


def test_search_absorbs_coordinates_and_standalone_card_is_gone():
    html = render_page("csrf", no_auth=True)
    assert "<h3>输入坐标</h3>" not in html
    assert 'id="coord-lat"' not in html
    assert 'id="coord-lon"' not in html
    assert 'id="coord-pair"' not in html
    assert 'id="coord-go"' not in html
    assert "function jumpToTypedCoords()" not in html
    assert "function parseCoordFields()" not in html
    assert "function parseCoordQuery(raw)" in html
    assert "function searchPlace()" in html or "async function searchPlace()" in html
    assert "已跳转到指定坐标" in html
    assert "输入地名（如：东京车站）或坐标（如：35.6812, 139.7671）" in html
    body = _js_function(html, "searchPlace")
    assert "parseCoordQuery(q)" in body
    assert "已跳转到指定坐标" in body
    # Coordinate hits must return before talking to Nominatim.
    assert body.index("parseCoordQuery") < body.index("nominatim.openstreetmap.org")
    assert body.index("已跳转到指定坐标") < body.index("nominatim.openstreetmap.org")
    parser = _js_function(html, "parseCoordQuery")
    assert "-90" in parser or "90" in parser
    assert "180" in parser
    assert "NSns" in parser and "EWew" in parser
    assert "[，、；;]" in parser
