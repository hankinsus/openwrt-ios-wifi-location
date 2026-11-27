from __future__ import annotations

import binascii
import json
import os
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ios_wifi_loc.coords import CoordError
from ios_wifi_loc.doctor import _ipv4_ioctl
from ios_wifi_loc.guide import pair_guide
from ios_wifi_loc.identifiers import IdentifierError, validate_name
from ios_wifi_loc.logs import append_log
from ios_wifi_loc.pairing import (
    PairingError,
    default_runtime_lockdown,
    delete_plist,
    import_plist,
    list_pairing,
)
from ios_wifi_loc.session import (
    clear_location,
    reconnect,
    refresh_devices,
    select_device,
    set_location,
    status,
)
from ios_wifi_loc.shortcut import ShortcutError, format_shortcut_status, shortcut_clear, shortcut_set
from ios_wifi_loc.sharelinks import ShareLinkError
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page
from ios_wifi_loc.windows_pair import ToolError, render_windows_pair_bat, server_base_from_host

DEFAULT_PORT = 47321



def _session_ui_fields(sess: dict | None) -> dict:
    if not sess:
        return {
            "session_alive": False,
            "holding": False,
            "watchdog_active": False,
            "waiting_reconnect": False,
            "reconnect_count": 0,
            "last_reconnect_at": None,
            "last_error": None,
        }
    alive = bool(sess.get("alive"))
    waiting = bool(sess.get("waiting_reconnect") or (sess.get("watchdog_active") and alive and not sess.get("holding")))
    try:
        reconnect_count = int(sess.get("reconnect_count") or 0)
    except (TypeError, ValueError):
        reconnect_count = 0
    return {
        "session_alive": alive,
        "holding": bool(sess.get("holding")),
        "watchdog_active": bool(sess.get("watchdog_active") and alive),
        "waiting_reconnect": waiting,
        "reconnect_count": reconnect_count,
        "last_reconnect_at": sess.get("last_reconnect_at"),
        "last_error": sess.get("last_error"),
        "latitude": sess.get("latitude"),
        "longitude": sess.get("longitude"),
    }


def _devices_with_sessions(devices: list, sessions: list) -> list[dict]:
    by_udid = {item.get("udid"): dict(item) for item in sessions if isinstance(item, dict) and item.get("udid")}
    result = []
    seen = set()
    for device in devices:
        if not isinstance(device, dict) or not device.get("udid"):
            continue
        item = dict(device)
        sess = by_udid.get(item["udid"])
        item.update(_session_ui_fields(sess))
        result.append(item)
        seen.add(item["udid"])
    for udid, sess in by_udid.items():
        if udid in seen:
            continue
        item = {
            "udid": udid,
            "name": None,
            "connection": "wifi",
            "transport": "mobdev2",
            "source": "session",
            "host": None,
            "product_version": None,
            "tunnel_ready": False,
        }
        item.update(_session_ui_fields(sess))
        result.append(item)
    return result


def enrich_pairing(report: dict, data: dict) -> dict:
    names = dict(data.get("device_names") or {})
    for item in data.get("discovery") or []:
        if not isinstance(item, dict) or not item.get("udid"):
            continue
        entry = dict(names.get(item["udid"]) or {})
        if item.get("name"):
            entry["name"] = item["name"]
        if item.get("product_version"):
            entry["product_version"] = item["product_version"]
        if entry:
            names[item["udid"]] = entry
    selected = data.get("selected") or {}
    if isinstance(selected, dict) and selected.get("udid"):
        entry = dict(names.get(selected["udid"]) or {})
        if selected.get("name"):
            entry["name"] = selected["name"]
        if selected.get("product_version"):
            entry["product_version"] = selected["product_version"]
        if entry:
            names[selected["udid"]] = entry
    files = []
    for item in report.get("files") or []:
        row = dict(item)
        if row.get("system_configuration"):
            row["device_name"] = None
            row["product_version"] = None
            row["display_name"] = "系统配对配置"
            row["label"] = "系统配对配置"
        else:
            meta = names.get(row.get("udid") or "") or {}
            row["device_name"] = meta.get("name")
            row["product_version"] = meta.get("product_version")
            title = meta.get("name") or "未命名设备"
            version = (" iOS " + str(meta["product_version"])) if meta.get("product_version") else ""
            row["display_name"] = (title + version).strip()
            row["label"] = row["display_name"]
        files.append(row)
    enriched = dict(report)
    enriched["files"] = files
    return enriched


class ServiceError(ValueError):
    pass


def secret_path(state_dir: Path) -> Path:
    return state_dir / "web.secret"


def runtime_lockdown_dir() -> Path | None:
    env = os.environ.get("IOS_WIFI_LOC_LOCKDOWN_DIR")
    if env == "":
        return None
    if env:
        return Path(env)
    path = default_runtime_lockdown()
    if path.is_dir() and os.access(path, os.W_OK):
        return path
    return None


def load_or_create_secret(path: Path) -> str:
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) < 16 or any(ch.isspace() for ch in value):
            raise ServiceError("口令文件已存在但内容不可用")
        os.chmod(path, 0o600)
        return value
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    value = secrets.token_urlsafe(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
    os.chmod(path, 0o600)
    return value


def resolve_bind(host: str | None, interface: str | None) -> str:
    if host in {"0.0.0.0", "::", "::0", ""}:
        raise ServiceError("拒绝监听 0.0.0.0。局域网访问要指定一块网卡。")
    if interface:
        if interface == "lo":
            return "127.0.0.1"
        address = _ipv4_ioctl(interface)
        if not address:
            raise ServiceError("指定的网卡没有 IPv4 地址")
        if address[0] in {"0.0.0.0", "255.255.255.255"}:
            raise ServiceError("网卡地址不能用来对全网监听")
        return address[0]
    if host in {None, "127.0.0.1", "localhost"}:
        return "127.0.0.1"
    raise ServiceError("局域网监听必须用 --interface 指定一块网卡，不能只写一个地址。")


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        items = [stamp for stamp in self._events.get(key, []) if now - stamp < window]
        if len(items) >= limit:
            self._events[key] = items
            return False
        items.append(now)
        self._events[key] = items[-limit:]
        if len(self._events) > 200:
            self._events.clear()
            self._events[key] = items[-limit:]
        return True


class Console:
    def __init__(self, store: StateStore, binary: str, secret: str, *, timeout: float = 20, grace: float = 2, require_auth: bool = False) -> None:
        self.store = store
        self.binary = binary
        self.secret = secret
        self.timeout = timeout
        self.grace = grace
        self.require_auth = require_auth
        self.sessions: dict[str, float] = {}
        self.rates = RateLimiter()
        self.log_path = store.directory / "service.log"

    def log(self, text: str) -> None:
        append_log(self.log_path, text, secret=self.secret)

    def payload(self, extra: dict | None = None) -> dict:
        current = status(self.store)
        data = dict(current.details)
        data["summary"] = current.summary
        state = self.store.load()
        data["devices"] = _devices_with_sessions(state.get("discovery") or [], data.get("sessions") or [])
        data["pairing"] = enrich_pairing(list_pairing(self.store.directory, runtime_dir=runtime_lockdown_dir()), state)
        data["device_names"] = state.get("device_names") or {}
        data["require_auth"] = self.require_auth
        if extra:
            data.update(extra)
        return data


def _cookies(header: str | None) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        found[key.strip()] = value.strip()
    return found


class Handler(BaseHTTPRequestHandler):
    console: Console
    expected_host: str

    def version_string(self) -> str:
        return "ios-wifi-loc"

    def log_message(self, fmt: str, *args: object) -> None:
        self.console.log("http " + (fmt % args))

    def _send(self, code: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict, headers: dict[str, str] | None = None) -> None:
        safe = json.dumps(payload, ensure_ascii=False).replace(self.console.secret, "[已隐藏]")
        self._send(code, safe.encode("utf-8"), "application/json; charset=utf-8", headers)

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "").lower() == self.expected_host.lower()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin == "http://" + self.expected_host

    def _csrf_ok(self) -> bool:
        cookies = _cookies(self.headers.get("Cookie"))
        token = cookies.get("csrf", "")
        return bool(token) and token == (self.headers.get("X-CSRF-Token") or "")

    def _session_ok(self) -> bool:
        if not self.console.require_auth:
            return True
        cookies = _cookies(self.headers.get("Cookie"))
        token = cookies.get("session", "")
        expiry = self.console.sessions.get(token)
        if not token or expiry is None or expiry < time.time():
            self.console.sessions.pop(token, None)
            return False
        return True

    def _split_path(self) -> tuple[str, dict[str, str]]:
        parsed = urlparse(self.path)
        query = {key: values[-1] if values else "" for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        return parsed.path, query

    def _token_from(self, query: dict[str, str] | None = None) -> str:
        header = (self.headers.get("X-API-Token") or self.headers.get("Authorization") or "").strip()
        if header.lower().startswith("bearer "):
            header = header[7:].strip()
        return str((query or {}).get("token") or header or "").strip()

    def _api_authorized(self, query: dict[str, str] | None = None) -> bool:
        if not self.console.require_auth:
            return True
        if self._session_ok():
            return True
        token = self._token_from(query)
        if not token:
            return False
        return secrets.compare_digest(token, self.console.secret)

    def _csrf_required(self) -> bool:
        return self.console.require_auth

    def _client(self) -> str:
        return self.client_address[0]

    def _read_json(self, max_length: int = 16384) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0 or length > max_length:
            raise ServiceError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ServiceError("请求不是 JSON") from exc
        if not isinstance(data, dict):
            raise ServiceError("请求必须是对象")
        return data

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._json(400, {"summary": "Host 不被接受"})
            return
        path, query = self._split_path()
        if path == "/":
            cookies = _cookies(self.headers.get("Cookie"))
            csrf = cookies.get("csrf") or secrets.token_hex(16)
            page = render_page(csrf, no_auth=not self.console.require_auth).encode("utf-8")
            self._send(200, page, "text/html; charset=utf-8", {"Set-Cookie": f"csrf={csrf}; Path=/; SameSite=Strict"})
            return
        if path in {"/api/tools/windows-pair.bat", "/api/tools/windows-pair.ps1"}:
            if not self._api_authorized(query):
                self._json(401, {"summary": "需要先输入本机口令或在 URL 里加上 token"})
                return
            self._windows_pair_tool()
            return
        if path.startswith("/api/shortcut/"):
            if not self._api_authorized(query):
                self._json(401, {"summary": "需要先输入本机口令或在 URL 里加上 token"})
                return
            self._handle_shortcut(path, query, {})
            return
        if not self._session_ok():
            self._json(401, {"summary": "需要先输入本机口令"})
            return
        if path == "/api/status":
            self._json(200, self.console.payload())
            return
        if path == "/api/guide":
            self._json(200, {"text": pair_guide()})
            return
        if path == "/api/pairing":
            self._json(200, self.console.payload())
            return
        self._json(404, {"summary": "没有这个页面"})

    def _post_guarded(self) -> bool:
        if not self._host_ok():
            return False
        if self.console.require_auth:
            return self._origin_ok() and self._csrf_ok()
        origin = self.headers.get("Origin")
        if origin and not self._origin_ok():
            return False
        if self._csrf_required() and not self._csrf_ok():
            return False
        # In no-auth mode a CSRF header is optional so LAN tools can call the API
        # directly. If the browser sent one, it must still match the cookie.
        token = self.headers.get("X-CSRF-Token")
        if token and not self._csrf_ok():
            return False
        return True

    def do_POST(self) -> None:  # noqa: N802
        path, query = self._split_path()
        open_api = path.startswith("/api/shortcut/") or path == "/api/pairing/import"
        if open_api:
            if not self._host_ok():
                self._json(400, {"summary": "Host 不被接受"})
                return
            if not self._api_authorized(query):
                self._json(401, {"summary": "需要先输入本机口令或在 URL 里加上 token"})
                return
        elif not self._post_guarded():
            self._json(403, {"summary": "请求来源没有通过校验"})
            return
        if not self.console.rates.allow("post:" + self._client(), 60, 60):
            self._json(429, {"summary": "请求过于频繁"})
            return
        try:
            max_length = 400 * 1024 if path == "/api/pairing/import" else 16384
            if (self.headers.get("Content-Type") or "").startswith("application/x-www-form-urlencoded"):
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length else b""
                form = {k: v[-1] if v else "" for k, v in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()}
                body = form
            else:
                body = self._read_json(max_length=max_length)
            if path.startswith("/api/shortcut/"):
                self._handle_shortcut(path, query, body)
                return
            if path == "/api/login":
                self._login(body)
                return
            if not open_api and not self._session_ok():
                self._json(401, {"summary": "需要先输入本机口令"})
                return
            if path == "/api/logout":
                cookies = _cookies(self.headers.get("Cookie"))
                self.console.sessions.pop(cookies.get("session", ""), None)
                self._json(200, {"summary": "已退出"}, {"Set-Cookie": "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
                return
            if path == "/api/discover":
                refresh_devices(self.console.store, self.console.binary, timeout=self.console.timeout)
                self._json(200, self.console.payload())
                return
            if path == "/api/select":
                outcome = select_device(
                    self.console.store,
                    udid=str(body.get("udid") or ""),
                    transport=body.get("transport"),
                    host=body.get("host") or None,
                    name=(str(body["name"]) if body.get("name") else None),
                    allow_usb=False,
                    usbmux_address=None,
                )
                self._json(200 if outcome.ok else 400, self.console.payload({"summary": outcome.summary}))
                return
            if path == "/api/favorites":
                self._add_favorite(body)
                return
            if path in {"/api/location/start", "/api/set"}:
                self._start(body)
                return
            if path in {"/api/location/clear", "/api/clear"}:
                self._clear(body)
                return
            if path == "/api/favorites/delete":
                self._delete_favorite(body)
                return
            if path == "/api/pairing/import":
                self._import_pairing(body)
                return
            if path == "/api/connection/check":
                outcome = reconnect(
                    self.console.store,
                    self.console.binary,
                    attempts=3,
                    timeout=min(self.console.timeout, 8),
                    pause=0.2,
                    resume=False,
                    latitude=None,
                    longitude=None,
                    profile="ios17",
                    grace=self.console.grace,
                    allow_usb=False,
                    allow_legacy=False,
                )
                self._json(200, self.console.payload({"summary": outcome.summary}))
                return
        except (ServiceError, IdentifierError, CoordError, PairingError) as exc:
            self._json(400, {"summary": str(exc)})
            return
        self._json(404, {"summary": "没有这个操作"})

    def _login(self, body: dict) -> None:
        if not self.console.rates.allow("login:" + self._client(), 8, 60):
            self._json(429, {"summary": "登录尝试过多"})
            return
        given = str(body.get("password") or "")
        if not secrets.compare_digest(given, self.console.secret):
            self.console.log("登录失败")
            self._json(401, {"summary": "口令不正确"})
            return
        token = secrets.token_hex(24)
        self.console.sessions[token] = time.time() + 12 * 3600
        self.console.log("登录成功")
        self._json(200, {"summary": "已进入"}, {"Set-Cookie": f"session={token}; Path=/; HttpOnly; SameSite=Strict"})

    def _add_favorite(self, body: dict) -> None:
        from ios_wifi_loc.coords import parse_pair

        name = validate_name(str(body.get("name") or ""))
        if not name:
            raise ServiceError("收藏需要名称")
        latitude, longitude = parse_pair(str(body.get("latitude") or ""), str(body.get("longitude") or ""))
        data = self.console.store.load()
        favorites = list(data.get("favorites") or [])
        if len(favorites) >= 50:
            raise ServiceError("收藏已达上限")
        favorites.append({"id": secrets.token_hex(8), "name": name, "latitude": latitude, "longitude": longitude})
        data["favorites"] = favorites
        self.console.store.save(data)
        self._json(200, self.console.payload())

    def _start(self, body: dict) -> None:
        if body.get("confirm") is not True:
            raise ServiceError("启动定位需要确认。服务不会在重启后自动重放坐标。")
        replace = True if body.get("replace") is None else bool(body.get("replace"))
        outcome = set_location(
            self.console.store,
            self.console.binary,
            latitude=str(body.get("latitude") or ""),
            longitude=str(body.get("longitude") or ""),
            profile=str(body.get("profile") or "ios17"),
            timeout=self.console.timeout,
            grace=self.console.grace,
            foreground=False,
            allow_usb=False,
            allow_legacy=False,
            replace=replace,
        )
        self.console.log(outcome.summary)
        self._json(200 if outcome.ok else 400, self.console.payload({"summary": outcome.summary}))

    def _clear(self, body: dict) -> None:
        if body.get("confirm") is not True:
            raise ServiceError("恢复定位需要确认")
        profile = body.get("profile")
        outcome = clear_location(
            self.console.store,
            self.console.binary,
            timeout=self.console.timeout,
            allow_usb=False,
            profile=None if profile in {None, "", "auto"} else str(profile),
        )
        self.console.log(outcome.summary)
        self._json(200 if outcome.ok else 400, self.console.payload({"summary": outcome.summary}))



    def _delete_favorite(self, body: dict) -> None:
        target = str(body.get("id") or "")
        if not target:
            raise ServiceError("缺少收藏编号")
        data = self.console.store.load()
        favorites = [item for item in (data.get("favorites") or []) if item.get("id") != target]
        if len(favorites) == len(data.get("favorites") or []):
            raise ServiceError("没有这个收藏")
        data["favorites"] = favorites
        self.console.store.save(data)
        self._json(200, self.console.payload())

    def _import_pairing(self, body: dict) -> None:
        files = body.get("files")
        if files is None and body.get("filename"):
            files = [body]
        if not isinstance(files, list) or not files:
            raise ServiceError("请上传至少一个 .plist 文件")
        if len(files) > 8:
            raise ServiceError("一次最多导入 8 个文件")
        imported = []
        runtime = runtime_lockdown_dir()
        for item in files:
            if not isinstance(item, dict):
                raise ServiceError("文件项无效")
            filename = str(item.get("filename") or "")
            raw = item.get("content_base64") or item.get("content") or ""
            if not isinstance(raw, str) or not raw.strip():
                raise ServiceError(f"{filename or '文件'} 内容是空的")
            import base64
            try:
                data = base64.b64decode(raw, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ServiceError("不是有效的 Base64 内容") from exc
            report = import_plist(self.console.store.directory, filename, data, runtime_dir=runtime)
            imported.append(report["imported"])
        self.console.log("已导入配对文件 " + ", ".join(imported))
        self._json(200, self.console.payload({"summary": "已导入 " + "、".join(imported), "imported": imported}))

    def _shortcut_reply(self, payload: dict, query: dict[str, str]) -> None:
        ok = bool(payload.get("ok", True))
        code = 200 if ok else 400
        fmt = (query.get("format") or "").lower()
        accept = (self.headers.get("Accept") or "").lower()
        if fmt in {"text", "plain", "txt"} or (fmt != "json" and accept.startswith("text/plain")):
            text = str(payload.get("text") or payload.get("summary") or "")
            self._send(code, (text + "\n").encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._json(code, payload)

    def _handle_shortcut(self, path: str, query: dict[str, str], body: dict) -> None:
        params = dict(query)
        if isinstance(body, dict):
            for key, value in body.items():
                if value is not None and value != "":
                    params[key] = value
        try:
            if path == "/api/shortcut/set":
                payload = shortcut_set(
                    self.console.store,
                    self.console.binary,
                    params,
                    timeout=self.console.timeout,
                    grace=self.console.grace,
                )
                self.console.log(payload.get("summary") or "")
                self._shortcut_reply(payload, query)
                return
            if path == "/api/shortcut/clear":
                payload = shortcut_clear(
                    self.console.store,
                    self.console.binary,
                    params,
                    timeout=self.console.timeout,
                )
                self.console.log(payload.get("summary") or "")
                self._shortcut_reply(payload, query)
                return
            if path == "/api/shortcut/status":
                payload = format_shortcut_status(self.console.store, udid=params.get("udid"))
                self._shortcut_reply(payload, query)
                return
        except (ShortcutError, ShareLinkError, CoordError, IdentifierError, PairingError) as exc:
            self._shortcut_reply({"ok": False, "code": "SHORTCUT_FAILED", "summary": str(exc), "text": str(exc)}, query)
            return
        self._json(404, {"summary": "没有这个快捷指令接口"})

    def _windows_pair_tool(self) -> None:
        host = self.headers.get("Host") or ""
        try:
            base = server_base_from_host(host, scheme="http")
            script = render_windows_pair_bat(base)
        except ToolError as exc:
            self._json(400, {"summary": str(exc)})
            return
        body = b"\xef\xbb\xbf" + script.encode("utf-8")
        self._send(
            200,
            body,
            "application/octet-stream; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="ios-wifi-loc-windows-pair.bat"'},
        )

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._post_guarded():
            self._json(403, {"summary": "请求来源没有通过校验"})
            return
        if not self._session_ok():
            self._json(401, {"summary": "需要先输入本机口令"})
            return
        path, _query = self._split_path()
        prefix = "/api/pairing/"
        if not path.startswith(prefix) or path == "/api/pairing/import":
            self._json(404, {"summary": "没有这个操作"})
            return
        name = unquote(path[len(prefix):])
        try:
            report = delete_plist(self.console.store.directory, name, runtime_dir=runtime_lockdown_dir())
        except PairingError as exc:
            self._json(400, {"summary": str(exc)})
            return
        self._json(200, self.console.payload({"summary": f"已删除 {report['deleted']}"}))


def watch_connection(stop: threading.Event, console: Console, *, interval: float = 10) -> None:
    remaining = 3
    while not stop.wait(0):
        status(console.store)
        delay = interval
        selected = (console.store.load().get("selected") or {}).get("udid")
        if selected and remaining > 0:
            refresh_devices(console.store, console.binary, timeout=min(console.timeout, 8))
            seen = any(
                item.get("udid") == selected and item.get("connection") == "wifi"
                for item in console.store.load().get("discovery") or []
            )
            if seen:
                remaining = 0
            else:
                remaining -= 1
                delay = min(8, 2 ** (3 - remaining))
        if stop.wait(delay):
            return


def acquire_lock(directory: Path):
    import fcntl

    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    handle = open(directory / "serve.lock", "a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise ServiceError("控制台已在运行") from exc
    os.chmod(directory / "serve.lock", 0o600)
    return handle


def serve(
    store: StateStore,
    binary: str,
    *,
    host: str | None = None,
    interface: str | None = None,
    port: int = DEFAULT_PORT,
    timeout: float = 20,
    grace: float = 2,
    watch: bool = True,
    watch_interval: float = 10,
    require_auth: bool = False,
) -> None:
    bind = resolve_bind(host, interface)
    secret = load_or_create_secret(secret_path(store.directory))
    lock = acquire_lock(store.directory)
    console = Console(store, binary, secret, timeout=timeout, grace=grace, require_auth=require_auth)
    status(store)
    handler = type("BoundHandler", (Handler,), {"console": console, "expected_host": ""})
    server = ThreadingHTTPServer((bind, port), handler)
    handler.expected_host = f"{bind}:{server.server_address[1]}"
    stop = threading.Event()
    watcher = None
    if watch:
        watcher = threading.Thread(target=watch_connection, args=(stop, console), kwargs={"interval": watch_interval}, daemon=True)
        watcher.start()
    print(f"LISTENING {bind} {server.server_address[1]}", flush=True)
    console.log(f"监听 {bind} {server.server_address[1]}")

    def _stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        stop.set()
        server.server_close()
        lock.close()
