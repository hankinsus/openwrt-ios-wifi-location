from __future__ import annotations

import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from ios_wifi_loc.coords import CoordError, parse_pair
from ios_wifi_loc.discovery import command_failed, discover
from ios_wifi_loc.identifiers import IdentifierError, validate_name, validate_udid
from ios_wifi_loc.runner import holder_matches, interrupt_holder, pid_alive, run, spawn
from ios_wifi_loc.state import StateStore
from ios_wifi_loc.tunneld import query_tunneld, tunnel_ready_for
from ios_wifi_loc.upstream import (
    PlanError,
    Target,
    classify_product_version,
    extract_product_version,
    location_argv,
    lockdown_info_argv,
    uses_wireless_tunnel,
)


@dataclass
class Outcome:
    ok: bool
    code: str
    exit_code: int
    summary: str
    details: dict = field(default_factory=dict)


def _fail(code: str, exit_code: int, summary: str, **details: object) -> Outcome:
    return Outcome(False, code, exit_code, summary, details)


def _selected_target(data: dict, *, usbmux_address: str | None = None) -> Target:
    selected = data.get("selected")
    if not selected:
        raise PlanError("还没有显式选择设备")
    return Target(
        udid=selected["udid"],
        transport=selected["transport"],
        host=selected.get("host"),
        usbmux_address=usbmux_address if usbmux_address is not None else selected.get("usbmux_address"),
    )


def refresh_devices(store: StateStore, binary: str, *, timeout: float) -> Outcome:
    report = discover(binary, timeout=timeout)
    data = store.load()
    data["discovery"] = report["devices"]
    store.save(data)
    wifi = [item for item in report["devices"] if item["connection"] == "wifi"]
    usb = [item for item in report["devices"] if item["connection"] == "usb"]
    return Outcome(
        True,
        "LISTED",
        0,
        f"Wi-Fi 列表 {len(wifi)} 台，USB 列表 {len(usb)} 台。USB 设备不会被当作 Wi-Fi 目标。空列表只表示这次探测没有看到设备。",
        report,
    )


def select_device(
    store: StateStore,
    *,
    udid: str,
    transport: str | None,
    host: str | None,
    name: str | None,
    allow_usb: bool,
    usbmux_address: str | None,
) -> Outcome:
    try:
        checked = validate_udid(udid)
        display = validate_name(name)
    except IdentifierError as exc:
        return _fail("VALIDATION", 2, str(exc))
    data = store.load()
    known = {item["udid"]: item for item in data.get("discovery") or [] if isinstance(item, dict) and "udid" in item}
    record = known.get(checked)
    if record and record.get("connection") == "usb" and not allow_usb:
        return _fail("USB_REFUSED", 2, "该标识在最近一次列表里是 USB。Wi-Fi 控制不会改用它，除非显式传入 --allow-usb。")
    chosen = transport
    if chosen is None:
        if record and record.get("connection") == "wifi":
            chosen = "usbmux"
        else:
            return _fail("NEED_TRANSPORT", 2, "必须显式指定 --transport。工具不会在多台或未知设备里自动挑选。")
    try:
        target = Target(udid=checked, transport=chosen, host=host, usbmux_address=usbmux_address)
    except (PlanError, IdentifierError) as exc:
        return _fail("VALIDATION", 2, str(exc))
    connection = "usb" if record and record.get("connection") == "usb" else "wifi"
    data["selected"] = {
        "udid": target.udid,
        "transport": target.transport,
        "host": target.host,
        "usbmux_address": target.usbmux_address,
        "name": display,
        "connection": connection,
    }
    _sync_legacy_session(data)
    store.save(data)
    return Outcome(True, "SELECTED", 0, "已记录显式选择。这只写入本机状态，不会配对，也不会改定位。切换设备不会停止其它手机上正在保持的模拟。", data["selected"])


def clear_selection(store: StateStore) -> Outcome:
    data = store.load()
    data["selected"] = None
    store.save(data)
    return Outcome(True, "UNSELECTED", 0, "已清除本机记录的设备选择。配对资料不在这里，也没有被删除。", {})


def _guard_selected(data: dict, *, allow_usb: bool) -> Outcome | None:
    selected = data.get("selected")
    if not selected:
        return _fail("NOT_SELECTED", 3, "必须先显式选择设备，再执行这个操作。")
    if selected.get("connection") == "usb" and not allow_usb:
        return _fail("USB_REFUSED", 2, "当前选择来自 USB 列表。Wi-Fi 定位命令已拒绝；如确要使用 USB，请再加 --allow-usb。")
    return None


def _probe_kind(binary: str, target: Target, timeout: float) -> tuple[str | None, object]:
    result = run(lockdown_info_argv(binary, target), timeout=timeout)
    if not result.ok:
        return None, result
    version = extract_product_version(result.stdout)
    if version is None:
        return None, result
    try:
        return classify_product_version(version), result
    except PlanError:
        return None, result


def _read_tail(path: Path) -> str:
    if not path.exists():
        return ""
    raw = path.read_bytes()[-2048:]
    from ios_wifi_loc.redact import redact

    return redact(raw.decode("utf-8", "replace"))


def _remember(store: StateStore, outcome: Outcome) -> Outcome:
    data = store.load()
    data["last_command"] = {
        "accepted": outcome.ok and outcome.code in {"SET_HOLDING", "SET_RETURNED", "CLEARED"},
        "code": outcome.code,
        "summary": outcome.summary,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    store.save(data)
    return outcome


def _sessions_map(data: dict) -> dict:
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
    selected = data.get("selected") or {}
    legacy = data.get("session")
    udid = selected.get("udid") if isinstance(selected, dict) else None
    if isinstance(legacy, dict):
        legacy_udid = legacy.get("udid")
        if legacy_udid and legacy_udid not in sessions:
            migrated = dict(legacy)
            migrated["udid"] = legacy_udid
            sessions[legacy_udid] = migrated
        elif (not legacy_udid) and udid and udid not in sessions:
            # Pre-0.3.0 records had a single session and no udid field.
            migrated = dict(legacy)
            migrated["udid"] = udid
            sessions[udid] = migrated
    data["sessions"] = sessions
    return sessions


def _session_for(data: dict, udid: str | None = None) -> dict | None:
    sessions = _sessions_map(data)
    if udid is None:
        selected = data.get("selected") or {}
        udid = selected.get("udid") if isinstance(selected, dict) else None
    if udid and udid in sessions:
        return sessions[udid]
    if udid is None:
        return data.get("session")
    return None


def _put_session(data: dict, udid: str, session: dict | None) -> None:
    sessions = _sessions_map(data)
    if session is None:
        sessions.pop(udid, None)
    else:
        stored = dict(session)
        stored["udid"] = udid
        sessions[udid] = stored
    data["sessions"] = sessions
    selected = data.get("selected") or {}
    if isinstance(selected, dict) and selected.get("udid") == udid:
        data["session"] = None if session is None else sessions.get(udid)


def _sync_legacy_session(data: dict) -> None:
    selected = data.get("selected") or {}
    udid = selected.get("udid") if isinstance(selected, dict) else None
    sessions = _sessions_map(data)
    data["session"] = sessions.get(udid) if udid else data.get("session")


def _release_stale_holder(store: StateStore, data: dict) -> dict:
    sessions = _sessions_map(data)
    changed = False
    for udid, session in list(sessions.items()):
        if not session or not session.get("pid"):
            continue
        pid = int(session["pid"])
        if holder_matches(pid):
            continue
        session = dict(session)
        session["pid"] = None
        session["holding"] = False
        session["ended_reason"] = "not_running" if not pid_alive(pid) else "cmdline_mismatch"
        sessions[udid] = session
        changed = True
    data["sessions"] = sessions
    _sync_legacy_session(data)
    if changed:
        store.save(data)
    return data


def _session_logs(store: StateStore, udid: str) -> tuple[Path, Path]:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in udid)
    return store.directory / f"session.{safe}.stdout", store.directory / f"session.{safe}.stderr"



def _plan_location(binary: str, target: Target, action: str, profile: str, latitude: str | None = None, longitude: str | None = None, *, tunneld: dict | None = None) -> tuple[list[str] | None, "Outcome | None", dict]:
    info = tunneld if tunneld is not None else query_tunneld()
    use_tunnel = False
    if uses_wireless_tunnel(target, profile):
        if not info.get("reachable"):
            return None, _fail(
                "TUNNELD_REQUIRED",
                4,
                "iOS 17+ 无线定位需要本机 tunneld 正在运行（默认 http://127.0.0.1:49151/）。请确认服务已启动，或在页面里启动隧道守护进程。",
                tunneld=info,
            ), info
        use_tunnel = True
    try:
        argv = location_argv(binary, target, action, profile, latitude, longitude, use_tunnel=use_tunnel)
    except PlanError as exc:
        return None, _fail("VALIDATION", 2, str(exc), tunneld=info), info
    return argv, None, info


def _apply_location(
    store: StateStore,
    binary: str,
    *,
    latitude: str,
    longitude: str,
    profile: str,
    timeout: float,
    grace: float,
    foreground: bool,
    allow_usb: bool,
    allow_legacy: bool,
    usbmux_address: str | None = None,
) -> Outcome:
    try:
        lat, lon = parse_pair(latitude, longitude)
    except CoordError as exc:
        return _fail("VALIDATION", 2, str(exc))
    if profile not in {"auto", "pre17", "ios17"}:
        return _fail("VALIDATION", 2, "profile 只能是 auto、pre17 或 ios17")
    if grace < 0.05 or grace > 30:
        return _fail("VALIDATION", 2, "启动观察时间必须在 0.05 到 30 秒之间")
    data = store.load()
    blocked = _guard_selected(data, allow_usb=allow_usb)
    if blocked:
        return blocked
    data = _release_stale_holder(store, data)
    try:
        target = _selected_target(data, usbmux_address=usbmux_address)
    except (PlanError, IdentifierError) as exc:
        return _fail("VALIDATION", 2, str(exc))
    session = _session_for(data, target.udid) or {}
    if session.get("pid") and holder_matches(int(session["pid"])):
        return _fail("DUPLICATE_SESSION", 4, "该设备已有定位会话进程。先清除它，再发送新坐标。不会启动第二个会话。其它手机的模拟不受影响。")
    resolved = profile
    if profile == "auto":
        resolved, probe = _probe_kind(binary, target, timeout)
        if resolved is None:
            detail = command_failed(probe) if hasattr(probe, "timed_out") else "版本输出无法识别"
            return _fail(
                "VERSION_UNKNOWN",
                4,
                f"没有从设备读到可用的 ProductVersion（{detail}）。工具不会猜测 iOS 版本，请显式传入 --profile。",
            )
    tunneld = query_tunneld()
    if resolved == "ios17_needs_tunneld" and not allow_legacy and not tunneld.get("reachable"):
        return _fail(
            "LEGACY_TUNNEL_REQUIRED",
            4,
            "上游文档写明 Linux 上的 iOS 17.0–17.3 需要 tunneld。本机 tunneld 当前不可用，因此默认拒绝这一段。请先启动隧道守护进程，或显式传入 --allow-legacy-ios17。",
            tunneld=tunneld,
        )
    command_profile = "pre17" if resolved == "pre17" else "ios17"
    argv, blocked, tunneld = _plan_location(binary, target, "set", command_profile, lat, lon, tunneld=tunneld)
    if blocked:
        return blocked
    assert argv is not None
    if command_profile == "pre17":
        result = run(argv, timeout=timeout)
        if result.error == "binary_missing":
            return _fail("BINARY_MISSING", 7, "找不到上游可执行文件", stderr=result.stderr)
        if result.timed_out:
            return _fail("TIMEOUT", 5, "上游 set 超时。不能确认定位已被设置。", stderr=result.stderr)
        if not result.ok:
            return _fail("UPSTREAM_FAILED", 4, f"上游 set 失败，退出码 {result.returncode}。定位未被确认。", stderr=result.stderr)
        record = {
            "pid": None,
            "profile": "pre17",
            "udid": target.udid,
            "latitude": lat,
            "longitude": lon,
            "argv": argv[1:],
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "holding": False,
        }
        _put_session(data, target.udid, record)
        store.save(data)
        return Outcome(
            True,
            "SET_RETURNED",
            0,
            "上游 set 已返回 0。按上游说明，iOS 17 以下的设置会保持到 clear。这里没有手机可以证明坐标已经生效。",
            {"profile": "pre17", "latitude": lat, "longitude": lon, "udid": target.udid},
        )
    log_out, log_err = _session_logs(store, target.udid)
    try:
        proc = spawn(argv, stdout_path=log_out, stderr_path=log_err)
    except FileNotFoundError:
        return _fail("BINARY_MISSING", 7, "找不到上游可执行文件")
    except OSError as exc:
        return _fail("UPSTREAM_FAILED", 4, f"上游进程没有启动：{exc.errno}")
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    if proc.poll() is not None:
        tail = _read_tail(log_err)
        if proc.returncode == 0:
            return _fail(
                "SESSION_ENDED_EARLY",
                4,
                "iOS 17+ 的上游 set 按文档应保持到被中断，但进程已经提前退出。不能确认定位仍在模拟。",
                stderr=tail,
            )
        return _fail("UPSTREAM_FAILED", 4, f"上游 set 失败，退出码 {proc.returncode}。", stderr=tail)
    record = {
        "pid": proc.pid,
        "profile": "ios17",
        "udid": target.udid,
        "latitude": lat,
        "longitude": lon,
        "argv": argv[1:],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "holding": True,
    }
    data = store.load()
    _put_session(data, target.udid, record)
    store.save(data)
    if not foreground:
        return Outcome(
            True,
            "SET_HOLDING",
            0,
            "上游 set 进程仍在运行。这只说明本机进程还在；按上游文档，iOS 17+ 的模拟由该进程保持。手机是否接受坐标需要真机确认。其它已在模拟的手机不会被打断。",
            {"pid": proc.pid, "profile": "ios17", "latitude": lat, "longitude": lon, "udid": target.udid},
        )
    return _wait_foreground(store, binary, proc, timeout, allow_usb)


def set_location(
    store: StateStore,
    binary: str,
    *,
    latitude: str,
    longitude: str,
    profile: str,
    timeout: float,
    grace: float,
    foreground: bool,
    allow_usb: bool,
    allow_legacy: bool,
    usbmux_address: str | None = None,
) -> Outcome:
    return _remember(
        store,
        _apply_location(
            store,
            binary,
            latitude=latitude,
            longitude=longitude,
            profile=profile,
            timeout=timeout,
            grace=grace,
            foreground=foreground,
            allow_usb=allow_usb,
            allow_legacy=allow_legacy,
            usbmux_address=usbmux_address,
        ),
    )


def _wait_foreground(store: StateStore, binary: str, proc, timeout: float, allow_usb: bool) -> Outcome:
    stop = {"flag": False}

    def _handle(signum: int, _frame: object) -> None:
        stop["flag"] = True

    previous_int = signal.signal(signal.SIGINT, _handle)
    previous_term = signal.signal(signal.SIGTERM, _handle)
    print(f"READY {proc.pid}", flush=True)
    try:
        while proc.poll() is None and not stop["flag"]:
            time.sleep(0.05)
    except KeyboardInterrupt:
        stop["flag"] = True
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
    holder = {"signaled": False, "exited": proc.poll() is not None, "reason": "observed_exit"}
    if pid_alive(proc.pid):
        holder = interrupt_holder(proc.pid, wait_s=min(timeout, 5))
    cleanup = clear_location(store, binary, timeout=timeout, allow_usb=allow_usb, profile="ios17")
    confirmed = cleanup.ok and cleanup.code == "CLEARED"
    summary = cleanup.summary
    if not confirmed:
        summary = "收到退出信号后已尝试清理。" + cleanup.summary
    return Outcome(confirmed, cleanup.code if confirmed else "CLEANUP_UNCONFIRMED", 0 if confirmed else 6, summary, {"holder": holder, "clear": cleanup.details})


def _clear_location(
    store: StateStore,
    binary: str,
    *,
    timeout: float,
    allow_usb: bool,
    profile: str | None = None,
) -> Outcome:
    data = store.load()
    blocked = _guard_selected(data, allow_usb=allow_usb)
    if blocked:
        return blocked
    try:
        target_early = _selected_target(data)
        udid = target_early.udid
    except (PlanError, IdentifierError):
        udid = (data.get("selected") or {}).get("udid")
        target_early = None
    data = _release_stale_holder(store, data)
    session = _session_for(data, udid) if udid else (data.get("session") or None)
    holder = None
    if session and session.get("pid"):
        holder = interrupt_holder(int(session["pid"]), wait_s=min(timeout, 5))
        if holder.get("exited") and udid:
            session = dict(session)
            session["pid"] = None
            session["holding"] = False
            _put_session(data, udid, session)
            store.save(data)
    chosen = profile or (session or {}).get("profile")
    if chosen not in {"pre17", "ios17"}:
        return _fail(
            "NEED_PROFILE",
            2,
            "没有已知的命令族，不能猜测该调用哪一个 clear。请传入 --profile。不能确认已经恢复真实定位。",
            holder=holder,
        )
    try:
        target = _selected_target(data)
    except (PlanError, IdentifierError) as exc:
        return _fail("VALIDATION", 2, str(exc), holder=holder)
    argv, blocked, _tunneld = _plan_location(binary, target, "clear", chosen)
    if blocked:
        blocked.details["holder"] = holder
        return blocked
    assert argv is not None
    result = run(argv, timeout=timeout)
    if result.error == "binary_missing":
        return _fail("BINARY_MISSING", 7, "找不到上游可执行文件。不能确认已经恢复真实定位。", holder=holder)
    if result.timed_out:
        return _fail("TIMEOUT", 5, "上游 clear 超时。不能确认已经恢复真实定位。", holder=holder, stderr=result.stderr)
    if not result.ok:
        return _fail(
            "CLEANUP_UNCONFIRMED",
            6,
            f"已尝试清理，但上游 clear 退出码为 {result.returncode}。不能确认已经恢复真实定位。",
            holder=holder,
            stderr=result.stderr,
        )
    data = store.load()
    if udid:
        _put_session(data, udid, None)
    else:
        data["session"] = None
    store.save(data)
    return Outcome(
        True,
        "CLEARED",
        0,
        "清除命令已成功返回。按上游说明，这会停止模拟并回到真实定位；没有手机时，不能代替你在手机上确认。其它手机上的模拟未被改动。",
        {"holder": holder, "profile": chosen, "udid": udid},
    )


def clear_location(
    store: StateStore,
    binary: str,
    *,
    timeout: float,
    allow_usb: bool,
    profile: str | None = None,
) -> Outcome:
    return _remember(store, _clear_location(store, binary, timeout=timeout, allow_usb=allow_usb, profile=profile))


def _public_sessions(data: dict) -> list[dict]:
    items = []
    for udid, session in _sessions_map(data).items():
        if not isinstance(session, dict):
            continue
        item = dict(session)
        item["udid"] = udid
        item["alive"] = bool(session.get("pid") and holder_matches(int(session["pid"])))
        item["session_alive"] = item["alive"]
        items.append(item)
    return items


def status(store: StateStore) -> Outcome:
    data = store.load()
    data = _release_stale_holder(store, data)
    sessions = _public_sessions(data)
    selected = data.get("selected")
    selected_udid = selected.get("udid") if isinstance(selected, dict) else None
    session = _session_for(data, selected_udid)
    alive = bool(session and session.get("pid") and holder_matches(int(session["pid"])))
    last = data.get("last_command") or {}
    accepted = "已接受" if last.get("accepted") else "尚未接受或上次未成功"
    running = "仍在本机运行" if alive else "没有在运行"
    holding_count = sum(1 for item in sessions if item.get("alive") or (item.get("profile") == "pre17" and item.get("latitude")))
    tunneld = query_tunneld()
    tunnel_label = "隧道已就绪" if tunneld.get("reachable") else "隧道未运行"
    summary = (
        f"控制命令：{accepted}。当前设备会话进程：{running}。正在模拟 {holding_count} 台设备。tunneld：{tunnel_label}。"
        "手机定位：未能确认。进程是否存活不能代表手机上的坐标。"
    )
    if selected and selected.get("udid"):
        selected = dict(selected)
        selected["tunnel_ready"] = tunnel_ready_for(selected["udid"], tunneld)
    return Outcome(
        True,
        "STATUS",
        0,
        summary,
        {
            "selected": selected,
            "session": session,
            "sessions": sessions,
            "holder_alive": alive,
            "session_alive": alive,
            "command_accepted": bool(last.get("accepted")),
            "last_command": last,
            "favorites": data.get("favorites") or [],
            "phone_location": "unconfirmed",
            "tunneld": tunneld,
        },
    )


def reconnect(
    store: StateStore,
    binary: str,
    *,
    attempts: int,
    timeout: float,
    pause: float,
    resume: bool,
    latitude: str | None,
    longitude: str | None,
    profile: str,
    grace: float,
    allow_usb: bool,
    allow_legacy: bool,
) -> Outcome:
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1 or attempts > 3:
        return _fail("VALIDATION", 2, "重连次数必须是 1 到 3。")
    if pause < 0 or pause > 5:
        return _fail("VALIDATION", 2, "重连间隔必须在 0 到 5 秒。")
    data = store.load()
    blocked = _guard_selected(data, allow_usb=allow_usb)
    if blocked:
        return blocked
    udid = data["selected"]["udid"]
    notes = []
    found = False
    for attempt in range(1, attempts + 1):
        report = discover(binary, timeout=timeout)
        data = store.load()
        data["discovery"] = report["devices"]
        store.save(data)
        matched = [item for item in report["devices"] if item["connection"] == "wifi" and item["udid"] == udid]
        notes.append(
            {
                "attempt": attempt,
                "matched": bool(matched),
                "probes": [
                    {
                        "name": probe["name"],
                        "returncode": probe["returncode"],
                        "timed_out": probe["timed_out"],
                        "error": probe["error"],
                        "parse_error": probe["parse_error"],
                    }
                    for probe in report["probes"]
                ],
            }
        )
        if matched:
            found = True
            break
        if attempt < attempts and pause:
            time.sleep(pause)
    if not found:
        return _fail("NOT_FOUND", 3, "有限次重连后仍没有在 Wi-Fi 列表里看到已选择的设备。定位没有被修改。", attempts=notes)
    if not resume:
        return Outcome(True, "RECONNECTED", 0, "已重新看到所选 Wi-Fi 设备。没有修改定位。", {"attempts": notes})
    if latitude is None or longitude is None:
        return _fail("VALIDATION", 2, "重新设置定位必须再次显式传入经纬度。本次没有修改定位。", attempts=notes)
    resumed = set_location(
        store,
        binary,
        latitude=latitude,
        longitude=longitude,
        profile=profile,
        timeout=timeout,
        grace=grace,
        foreground=False,
        allow_usb=allow_usb,
        allow_legacy=allow_legacy,
    )
    resumed.details["attempts"] = notes
    return resumed


def smoke(
    store: StateStore,
    binary: str,
    *,
    latitude: str,
    longitude: str,
    profile: str,
    execute: bool,
    acknowledge: bool,
    timeout: float,
    grace: float,
    allow_usb: bool,
    allow_legacy: bool,
) -> Outcome:
    if not execute:
        if profile not in {"pre17", "ios17"}:
            return _fail("VALIDATION", 2, "演练必须显式给出 --profile pre17 或 ios17，这样才不会为了判断版本去连接手机。")
        data = store.load()
        blocked = _guard_selected(data, allow_usb=allow_usb)
        if blocked:
            return blocked
        try:
            lat, lon = parse_pair(latitude, longitude)
            target = _selected_target(data)
            argv, blocked, tunneld = _plan_location(binary, target, "set", profile, lat, lon)
            if blocked:
                return blocked
        except (CoordError, PlanError, IdentifierError) as exc:
            return _fail("VALIDATION", 2, str(exc))
        return Outcome(True, "DRY_RUN", 0, "演练：未调用上游，未修改定位。", {"argv": argv, "tunneld": tunneld})
    if not acknowledge:
        return _fail(
            "ACK_REQUIRED",
            2,
            "真机执行需要同时传入 --execute 和 --i-understand-this-sets-a-real-device，并显式给出经纬度。本次没有修改定位。",
        )
    return set_location(
        store,
        binary,
        latitude=latitude,
        longitude=longitude,
        profile=profile,
        timeout=timeout,
        grace=grace,
        foreground=False,
        allow_usb=allow_usb,
        allow_legacy=allow_legacy,
    )
