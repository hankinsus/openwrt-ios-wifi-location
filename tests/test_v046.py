from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ios_wifi_loc import __version__
from ios_wifi_loc.pairing import import_plist
from ios_wifi_loc.web_page import render_page

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fakes" / "pymobiledevice3"
UDID_A = "00008150-001A218E3A123801"
UDID_B = "00008120-001B218E3A123802"
PLIST = b"<?xml version='1.0'?><plist version='1.0'><dict></dict></plist>"
VIEWPORTS = (("phone", 390, 844), ("ipad", 820, 1180), ("desktop", 1440, 900))


def _inline_scripts(html: str) -> list[str]:
    scripts = []
    for match in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I):
        scripts.append(match.group(1))
    return scripts


def test_version_is_046():
    assert __version__ == "0.4.8"
    html = render_page("csrf", no_auth=True)
    assert "v0.4.8" in html
    assert "OpenWrt 无线虚拟定位 · v0.4.8" in html
    assert "v0.4.5" not in html


def test_map_is_full_bleed_and_cards_stay_narrow():
    html = render_page("csrf", no_auth=True)
    assert "#app { width:100%; max-width:none;" in html
    assert ".map-shell { width:100%; max-width:100%;" in html
    assert ".map-wrap { width:100%; max-width:100%;" in html
    assert "100vw" not in html
    assert "border-radius:0" in html
    assert "overflow:visible" in html
    assert "left:auto; right:12px;" in html
    assert "max-width:calc(100% - 56px)" in html
    assert "margin:28px auto 0 auto" in html
    assert "#map { height:420px;" in html
    assert "@media (max-width:1024px)" in html
    assert "@media (max-width:600px)" in html
    assert ".panel { padding:16px; max-width:720px;" in html
    assert "#login-card { max-width:720px;" in html
    assert "#action-error:empty" in html
    assert "display:none" in html[html.index("#action-error:empty") : html.index("#action-error:empty") + 80]


def test_paint_defines_ready_before_pairing_status():
    html = render_page("csrf", no_auth=True)
    paint = html[html.index("function paint(data)"): html.index("async function refresh(")]
    assert "const ready = !!(data && data.tunneld && data.tunneld.reachable);" in paint
    assert paint.index("const ready") < paint.index("无线隧道服务已就绪")
    assert "ready is not defined" not in html


def test_inline_javascript_passes_node_syntax_check(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    scripts = _inline_scripts(render_page("csrf-token", no_auth=True))
    assert scripts, "expected an inline script in the rendered page"
    source = "\n".join(scripts)
    script = tmp_path / "page.js"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout


def _start_console(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "favorites": [
                    {"id": "fav-home", "name": "家", "latitude": "39.75", "longitude": "-75.55"},
                    {"id": "fav-work", "name": "公司", "latitude": "35.6812", "longitude": "139.7671"},
                ],
                "device_names": {
                    UDID_A: {"name": "iPhone17 PRO", "product_version": "27.2.1"},
                    UDID_B: {"name": "iPhone 16", "product_version": "18.6.1"},
                },
                "selected": {"udid": UDID_A, "transport": "usbmux"},
                "discovery": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    import_plist(state, f"{UDID_A}.plist", PLIST)
    import_plist(state, "SystemConfiguration.plist", PLIST)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["IOS_WIFI_LOC_FAKE_LOG"] = str(tmp_path / "argv.log")
    env["IOS_WIFI_LOC_FAKE_DEVICES"] = json.dumps([UDID_A, UDID_B])
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ios_wifi_loc",
            "--state-dir",
            str(state),
            "--binary",
            str(FAKE),
            "serve",
            "--no-auth",
            "--no-watch",
            "--port",
            "0",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line.startswith("LISTENING "):
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(line + err)
    _listen, host, port = line.split()
    return proc, f"http://{host}:{port}/"


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _playwright_or_skip():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright is not installed")
    return sync_playwright



def _launch_chromium(playwright):
    last = None
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or "/usr/bin/google-chrome"
    attempts = [{}, {"channel": "chrome"}, {"executable_path": chrome}]
    for kwargs in attempts:
        try:
            return playwright.chromium.launch(headless=True, **kwargs)
        except Exception as exc:  # pragma: no cover - fallbacks
            last = exc
    pytest.skip(f"chromium is unavailable: {last}")


def test_three_viewports_render_and_interact_without_js_errors(tmp_path: Path):
    sync_playwright = _playwright_or_skip()
    proc, url = _start_console(tmp_path)
    failures: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = _launch_chromium(playwright)
            try:
                for name, width, height in VIEWPORTS:
                    failures.extend(_run_viewport(browser, url, name, width, height))
            finally:
                browser.close()
    finally:
        _stop(proc)
    assert not failures, "\n".join(failures)


def _run_viewport(browser, url: str, name: str, width: int, height: int) -> list[str]:
    errors: list[str] = []
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    page.on("pageerror", lambda exc: errors.append(f"{name} pageerror: {exc}"))
    page.on(
        "console",
        lambda msg: errors.append(f"{name} console.{msg.type}: {msg.text}")
        if msg.type == "error"
        else None,
    )
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("#app:not([hidden])", timeout=15000)
    page.wait_for_timeout(400)
    # Leaflet may need a moment after showApp().invalidateSize()
    page.wait_for_timeout(300)

    metrics = page.evaluate(
        """() => {
          const doc = document.documentElement;
          const map = document.querySelector(".map-wrap") || document.getElementById("map");
          const mapBox = map.getBoundingClientRect();
          const panel = document.querySelector(".panel");
          const panelBox = panel.getBoundingClientRect();
          const err = document.getElementById("action-error");
          const errBox = err ? err.getBoundingClientRect() : {height: 0};
          const emptyError = !err || !((err.textContent || "").trim());
          const isVisible = (el) => {
            const r = el.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) return false;
            const s = getComputedStyle(el);
            if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
            const details = el.closest("details");
            if (details && !details.open) {
              const summary = details.querySelector("summary");
              if (!summary || !summary.contains(el)) return false;
            }
            return true;
          };
          const buttons = [...document.querySelectorAll(".btn, .layer-btn, .fav-del")].filter(isVisible);
          const overlaps = [];
          for (let i = 0; i < buttons.length; i++) {
            const a = buttons[i].getBoundingClientRect();
            for (let j = i + 1; j < buttons.length; j++) {
              const b = buttons[j].getBoundingClientRect();
              const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
              const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
              if (x > 4 && y > 4) {
                overlaps.push(((buttons[i].id || buttons[i].innerText || "").trim().slice(0, 24)) + " x " + ((buttons[j].id || buttons[j].innerText || "").trim().slice(0, 24)));
              }
            }
          }
          const layers = [...document.querySelectorAll("#layers .layer-btn, .layer-switch .layer-btn")];
          const layerInfo = layers.map((el) => {
            const r = el.getBoundingClientRect();
            return { text: (el.innerText || "").trim(), left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height };
          });
          const bar = document.querySelector(".layer-switch, #layers");
          const barBox = bar ? bar.getBoundingClientRect() : {left:0,right:0,top:0,bottom:0,width:0,height:0};
          const zoom = document.querySelector(".leaflet-control-zoom, .leaflet-control-zoom-in");
          const zoomBox = zoom ? (zoom.classList && zoom.classList.contains("leaflet-control-zoom") ? zoom.getBoundingClientRect() : (zoom.closest(".leaflet-control-zoom") || zoom).getBoundingClientRect()) : {left:0,right:0,top:0,bottom:0,width:0,height:0};
          const zoomOverlapX = Math.max(0, Math.min(barBox.right, zoomBox.right) - Math.max(barBox.left, zoomBox.left));
          const zoomOverlapY = Math.max(0, Math.min(barBox.bottom, zoomBox.bottom) - Math.max(barBox.top, zoomBox.top));
          const footer = document.querySelector(".footer-card");
          const footerStyle = footer ? getComputedStyle(footer) : null;
          const footerGap = (footer && panel) ? (footer.getBoundingClientRect().top - panel.getBoundingClientRect().bottom) : -1;
          const cards = [...document.querySelectorAll("#app .card")];
          const lastCard = cards.length ? cards[cards.length - 1] : null;
          const footerAfter = (footer && lastCard) ? (footer.getBoundingClientRect().top - lastCard.getBoundingClientRect().bottom) : footerGap;
          return {
            scrollWidth: doc.scrollWidth,
            clientWidth: doc.clientWidth,
            innerWidth: window.innerWidth,
            mapWidth: mapBox.width,
            mapLeft: mapBox.left,
            mapHeight: mapBox.height,
            panelWidth: panelBox.width,
            errorHeight: emptyError ? errBox.height : -1,
            overlaps,
            layerInfo,
            footerMarginTop: footerStyle ? parseFloat(footerStyle.marginTop) || 0 : -1,
            footerBg: footerStyle ? footerStyle.backgroundColor : "",
            footerAfter,
            barLeft: barBox.left,
            barRight: barBox.right,
            barWidth: barBox.width,
            zoomLeft: zoomBox.left,
            zoomRight: zoomBox.right,
            zoomPresent: !!(zoom && zoomBox.width),
            zoomOverlap: zoomOverlapX > 2 && zoomOverlapY > 2,
          };
        }"""
    )
    if metrics["scrollWidth"] > metrics["clientWidth"] + 1:
        errors.append(
            f"{name} horizontal overflow: scrollWidth={metrics['scrollWidth']} clientWidth={metrics['clientWidth']}"
        )
    if abs(metrics["mapWidth"] - metrics["clientWidth"]) > 2 or abs(metrics["mapLeft"]) > 2:
        errors.append(
            f"{name} map is not full-bleed: width={metrics['mapWidth']} left={metrics['mapLeft']} clientWidth={metrics['clientWidth']}"
        )
    if name == "desktop":
        if metrics["panelWidth"] > 721:
            errors.append(f"{name} panel too wide: {metrics['panelWidth']}")
        if metrics["mapHeight"] < 380 or metrics["mapHeight"] > 440:
            errors.append(f"{name} map height {metrics['mapHeight']} not in 380-440")
    elif metrics["panelWidth"] > min(721, metrics["clientWidth"] + 1):
        errors.append(f"{name} panel too wide: {metrics['panelWidth']}")
    if metrics["errorHeight"] not in (-1, 0) and metrics["errorHeight"] > 1:
        errors.append(f"{name} empty action-error still takes space: {metrics['errorHeight']}")
    if metrics["overlaps"]:
        errors.append(f"{name} overlapping controls: {metrics['overlaps'][:8]}")
    layers = metrics.get("layerInfo") or []
    if len(layers) != 6:
        errors.append(f"{name} expected 6 layer buttons, got {len(layers)}: {layers}")
    else:
        vw = metrics.get("innerWidth") or metrics["clientWidth"]
        for item in layers:
            if item["width"] < 8 or item["height"] < 8:
                errors.append(f"{name} layer button {item['text']!r} not visible: {item}")
            if item["right"] > vw + 1 or item["left"] < -1:
                errors.append(
                    f"{name} layer button {item['text']!r} clipped: right={item['right']} left={item['left']} viewport={vw}"
                )
    if metrics.get("zoomPresent") and metrics.get("zoomOverlap"):
        errors.append(
            f"{name} layer bar covers zoom control: bar=({metrics.get('barLeft')},{metrics.get('barRight')}) zoom=({metrics.get('zoomLeft')},{metrics.get('zoomRight')})"
        )
    if metrics.get("barLeft", 0) < 40:
        errors.append(f"{name} layer bar is not a compact top-right chip: left={metrics.get('barLeft')} width={metrics.get('barWidth')}")
    if metrics.get("barWidth") and metrics.get("mapWidth") and metrics["barWidth"] > metrics["mapWidth"] - 40:
        errors.append(f"{name} layer bar spans the map: barWidth={metrics.get('barWidth')} mapWidth={metrics.get('mapWidth')}")
    if metrics.get("footerMarginTop", -1) < 24:
        errors.append(f"{name} footer margin-top too small: {metrics.get('footerMarginTop')}")
    if metrics.get("footerAfter", -1) >= 0 and metrics["footerAfter"] < 20:
        errors.append(f"{name} footer too close to the card above: gap={metrics['footerAfter']}")

    # Shared, non-destructive checks on every viewport.
    try:
        page.wait_for_function(
            "() => document.getElementById('device-select') && document.getElementById('device-select').options.length >= 3",
            timeout=10000,
        )
        page.select_option("#device-select", UDID_B)
        page.wait_for_function(
            "() => (document.getElementById('device-info-title') || {}).textContent.includes('iPhone 16')",
            timeout=8000,
        )
        page.select_option("#device-select", UDID_A)
        page.wait_for_function(
            "() => (document.getElementById('device-info-title') || {}).textContent.includes('iPhone17 PRO')",
            timeout=8000,
        )

        page.fill("#searchInput", "39.75, -75.55")
        page.click("#search")
        page.wait_for_function(
            "() => { const t = (document.getElementById('coords') || {}).textContent || ''; return t.includes('39.75') && t.includes('75.55'); }",
            timeout=5000,
        )

        page.click('.layer-btn[data-layer="wgs84"]')
        page.wait_for_function(
            "() => document.querySelector('.layer-btn[data-layer=\"wgs84\"]').classList.contains('active')",
            timeout=3000,
        )

        details = page.locator("details.pair-manual")
        if details.get_attribute("open") is not None:
            errors.append(f"{name} manual pairing details should start collapsed")
        details.locator("summary").click()
        page.wait_for_function("() => document.querySelector('details.pair-manual').open", timeout=3000)
        details.locator("summary").click()
        page.wait_for_function("() => !document.querySelector('details.pair-manual').open", timeout=3000)

        href = page.get_attribute("#download-windows-pair", "href") or ""
        if "/api/tools/windows-pair.bat" not in href:
            errors.append(f"{name} windows-pair href unexpected: {href!r}")
        set_link = page.locator("a", has_text="一键安装：地图分享定位")
        clear_link = page.locator("a", has_text="一键安装：恢复真实定位")
        if "icloud.com/shortcuts/" not in (set_link.get_attribute("href") or ""):
            errors.append(f"{name} shortcut set link missing")
        if "icloud.com/shortcuts/" not in (clear_link.get_attribute("href") or ""):
            errors.append(f"{name} shortcut clear link missing")
    except Exception as exc:
        errors.append(f"{name} interaction failed: {type(exc).__name__}: {exc}")

    # Destructive or stateful actions only on desktop so later viewports keep the same fixtures.
    if name == "desktop":
        try:
            page.click("#start")
            page.wait_for_function(
                """() => {
                  const t = (document.getElementById('device-status') || {}).textContent || '';
                  return t.includes('保持中') || t.includes('模拟中');
                }""",
                timeout=12000,
            )
            page.click("#add-fav")
            page.wait_for_selector("#favModal.show", timeout=5000)
            page.fill("#favNameInput", "测试点")
            page.click("#fav-save")
            page.wait_for_function(
                "() => (document.getElementById('favs') || {}).textContent.includes('测试点')",
                timeout=5000,
            )
            page.locator(".fav-item", has_text="测试点").locator(".fav-del").click()
            page.wait_for_function(
                "() => !(document.getElementById('favs') || {}).textContent.includes('测试点')",
                timeout=5000,
            )
            with page.expect_download(timeout=10000) as download_info:
                page.click("#download-windows-pair")
            download = download_info.value
            if "windows-pair" not in (download.suggested_filename or ""):
                errors.append(f"{name} unexpected download name: {download.suggested_filename!r}")
            if page.locator("#pair-files .fav-del").count() < 1:
                errors.append(f"{name} expected pairing delete buttons")
            else:
                before = page.locator("#pair-files .fav-del").count()
                page.locator("#pair-files .fav-del").first.click()
                page.wait_for_function(
                    f"() => document.querySelectorAll('#pair-files .fav-del').length < {before}",
                    timeout=5000,
                )
        except Exception as exc:
            errors.append(f"{name} stateful interaction failed: {type(exc).__name__}: {exc}")

    err_text = page.locator("#action-error").inner_text()
    if err_text.strip():
        errors.append(f"{name} action-error visible: {err_text.strip()!r}")

    context.close()
    return errors

import threading
import time

from ios_wifi_loc.install import install_files
from ios_wifi_loc.session import (
    Outcome,
    remember_desired_target,
    restore_desired_loop,
)
from ios_wifi_loc.state import StateStore


UDID_PERSIST = "0123456789abcdef0123456789abcdef01234567"


def test_selected_badge_shows_tunnel_connection_state():
    html = render_page("csrf", no_auth=True)
    assert "已连接" in html
    assert "未连接" in html
    assert "badge-connected" in html
    assert "badge-disconnected" in html
    assert 'picked.textContent = connected ? "已连接" : "未连接"' in html
    # The corner badge is no longer a static "已选择" label.
    assert ">已选择</span>" not in html
    assert "current.tunnel_connected || current.tunnel_ready" in html


def test_restore_loop_retries_until_saved_target_is_holding(tmp_path: Path):
    store = StateStore(tmp_path / "state")
    remember_desired_target(
        store,
        udid=UDID_PERSIST,
        lat="39.75",
        lon="-75.55",
        profile="ios17",
        transport="mobdev2",
    )
    attempts = {"n": 0}
    holding_ok = {"ok": False}

    def apply(item):
        attempts["n"] += 1
        assert item["udid"] == UDID_PERSIST
        assert item["lat"] == "39.75"
        if attempts["n"] < 3:
            return Outcome(False, "TUNNELD_REQUIRED", 4, "tunneld 还没就绪")
        holding_ok["ok"] = True
        return Outcome(True, "SET_HOLDING", 0, "ok", {"udid": item["udid"]})

    stop = threading.Event()
    thread = threading.Thread(
        target=restore_desired_loop,
        args=(stop, store, "pymobiledevice3"),
        kwargs={
            "timeout": 1,
            "grace": 0.05,
            "interval": 0.05,
            "apply": apply,
            "holding": lambda item, session: holding_ok["ok"],
        },
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and attempts["n"] < 3:
        time.sleep(0.02)
    assert attempts["n"] >= 3, f"restore loop did not retry until success: {attempts}"
    time.sleep(0.2)
    after = attempts["n"]
    time.sleep(0.25)
    assert attempts["n"] == after, "restore loop kept applying after the target was holding"
    stop.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_install_upgrade_preserves_desired_targets(tmp_path: Path):
    root = tmp_path / "root"
    (root / "etc/openwrt_release").parent.mkdir(parents=True)
    (root / "etc/openwrt_release").write_text("DISTRIB_ID='OpenWrt'\n", encoding="utf-8")
    state = tmp_path / "etc-ios-wifi-loc"
    state.mkdir()
    payload = {
        "version": 1,
        "desired_targets": {
            UDID_PERSIST: {
                "udid": UDID_PERSIST,
                "lat": "39.75",
                "lon": "-75.55",
                "latitude": "39.75",
                "longitude": "-75.55",
                "profile": "ios17",
                "enabled": True,
            }
        },
        "favorites": [{"id": "fav-home", "name": "家", "latitude": "39.75", "longitude": "-75.55"}],
    }
    path = state / "state.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    installed = install_files(root, state_dir=state, executable="python3")
    after = path.read_text(encoding="utf-8")
    saved = json.loads(after)
    assert after == before or saved["desired_targets"][UDID_PERSIST]["lat"] == "39.75"
    assert saved["desired_targets"][UDID_PERSIST]["lon"] == "-75.55"
    assert saved["favorites"][0]["name"] == "家"
    assert installed["init"] == "procd"
    script = Path(ROOT / "scripts" / "oneclick-install.sh").read_text(encoding="utf-8")
    assert "会保留已有口令、收藏和配对文件并重启服务" in script
    # Upgrade must never delete the persisted state file.
    assert "rm -rf \"$STATE\"" not in script
    assert "rm -f \"$STATE/state.json\"" not in script
    assert "rm \"$STATE/state.json\"" not in script
