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
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.web_page import render_page

DEFAULT_PORT = 47321



def _devices_with_sessions(devices: list, sessions: list) -> list[dict]:
    by_udid = {item.get("udid"): dict(item) for item in sessions if isinstance(item, dict) and item.get("udid")}
    result = []
    seen = set()
    for device in devices:
        if not isinstance(device, dict) or not device.get("udid"):
            continue
        item = dict(device)
        sess = by_udid.get(item["udid"])
        if sess:
            item["session_alive"] = bool(sess.get("alive"))
            item["holding"] = bool(sess.get("holding") or sess.get("alive"))
            item["latitude"] = sess.get("latitude")
            item["longitude"] = sess.get("longitude")
        else:
            item.setdefault("session_alive", False)
            item.setdefault("holding", False)
        result.append(item)
        seen.add(item["udid"])
    for udid, sess in by_udid.items():
        if udid in seen:
            continue
        result.append(
            {
                "udid": udid,
                "name": None,
                "connection": "wifi",
                "transport": "mobdev2",
                "source": "session",
                "host": None,
                "product_version": None,
                "tunnel_ready": False,
                "session_alive": bool(sess.get("alive")),
                "holding": bool(sess.get("holding") or sess.get("alive")),
                "latitude": sess.get("latitude"),
                "longitude": sess.get("longitude"),
            }
        )
    return result


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
        data["devices"] = _devices_with_sessions(self.store.load().get("discovery") or [], data.get("sessions") or [])
        data["pairing"] = list_pairing(self.store.directory, runtime_dir=runtime_lockdown_dir())
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
        if self.path == "/":
            cookies = _cookies(self.headers.get("Cookie"))
            csrf = cookies.get("csrf") or secrets.token_hex(16)
            page = render_page(csrf, no_auth=not self.console.require_auth).encode("utf-8")
            self._send(200, page, "text/html; charset=utf-8", {"Set-Cookie": f"csrf={csrf}; Path=/; SameSite=Strict"})
            return
        if not self._session_ok():
            self._json(401, {"summary": "需要先输入本机口令"})
            return
        if self.path == "/api/status":
            self._json(200, self.console.payload())
            return
        if self.path == "/api/guide":
            self._json(200, {"text": pair_guide()})
            return
        if self.path == "/api/pairing":
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
        if not self._post_guarded():
            self._json(403, {"summary": "请求来源没有通过校验"})
            return
        if not self.console.rates.allow("post:" + self._client(), 60, 60):
            self._json(429, {"summary": "请求过于频繁"})
            return
        try:
            max_length = 400 * 1024 if self.path == "/api/pairing/import" else 16384
            body = self._read_json(max_length=max_length)
            if self.path == "/api/login":
                self._login(body)
                return
            if not self._session_ok():
                self._json(401, {"summary": "需要先输入本机口令"})
                return
            if self.path == "/api/logout":
                cookies = _cookies(self.headers.get("Cookie"))
                self.console.sessions.pop(cookies.get("session", ""), None)
                self._json(200, {"summary": "已退出"}, {"Set-Cookie": "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
                return
            if self.path == "/api/discover":
                refresh_devices(self.console.store, self.console.binary, timeout=self.console.timeout)
                self._json(200, self.console.payload())
                return
            if self.path == "/api/select":
                outcome = select_device(
                    self.console.store,
                    udid=str(body.get("udid") or ""),
                    transport=body.get("transport"),
                    host=body.get("host") or None,
                    name=None,
                    allow_usb=False,
                    usbmux_address=None,
                )
                self._json(200 if outcome.ok else 400, self.console.payload({"summary": outcome.summary}))
                return
            if self.path == "/api/favorites":
                self._add_favorite(body)
                return
            if self.path in {"/api/location/start", "/api/set"}:
                self._start(body)
                return
            if self.path in {"/api/location/clear", "/api/clear"}:
                self._clear(body)
                return
            if self.path == "/api/favorites/delete":
                self._delete_favorite(body)
                return
            if self.path == "/api/pairing/import":
                self._import_pairing(body)
                return
            if self.path == "/api/connection/check":
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

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._post_guarded():
            self._json(403, {"summary": "请求来源没有通过校验"})
            return
        if not self._session_ok():
            self._json(401, {"summary": "需要先输入本机口令"})
            return
        prefix = "/api/pairing/"
        if not self.path.startswith(prefix) or self.path == "/api/pairing/import":
            self._json(404, {"summary": "没有这个操作"})
            return
        from urllib.parse import unquote
        name = unquote(self.path[len(prefix):])
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
