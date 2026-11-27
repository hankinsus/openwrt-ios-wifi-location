from __future__ import annotations

import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ios_wifi_loc.coords import CoordError, parse_pair
from ios_wifi_loc.discovery import command_failed, discover
from ios_wifi_loc.identifiers import IdentifierError, validate_name, validate_udid
from ios_wifi_loc.runner import (
    holder_matches,
    holder_process_counts,
    interrupt_holder,
    pid_alive,
    pids_matching,
    run,
    spawn,
    terminate_pids,
)
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


def merge_known_devices(existing: list | None, incoming: list | None) -> tuple[list[dict], list[str]]:
    """Keep previously known devices and update/add any that were just seen.

    Incoming live fields (host, transport, connection, tunnel_ready) overwrite
    stale ones; a generic later name will not erase a saved friendly name.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item in existing or []:
        if not isinstance(item, dict) or not item.get("udid"):
            continue
        udid = str(item["udid"])
        if udid not in merged:
            merged[udid] = dict(item)
            order.append(udid)
    added: list[str] = []
    for item in incoming or []:
        if not isinstance(item, dict) or not item.get("udid"):
            continue
        udid = str(item["udid"])
        if udid not in merged:
            merged[udid] = dict(item)
            order.append(udid)
            added.append(udid)
            continue
        current = dict(merged[udid])
        # Pairing records only fill empty fields; they must not invent or
        # overwrite a live/selected transport or host.
        fill_only = str(item.get("source") or "") == "pairing"
        for key, value in item.items():
            if value in (None, ""):
                continue
            if fill_only and current.get(key) not in (None, ""):
                continue
            if key in {"name", "device_name"}:
                incoming_name = str(value)
                kept = current.get("name")
                if is_generic_device_name(incoming_name) and kept and not is_generic_device_name(str(kept)):
                    continue
                current["name"] = preferred_device_name(incoming_name, kept) or incoming_name
                continue
            current[key] = value
        merged[udid] = current
    return [merged[udid] for udid in order], added


def remember_known_device(data: dict, item: dict | None) -> bool:
    if not isinstance(item, dict) or not item.get("udid"):
        return False
    merged, _added = merge_known_devices(data.get("discovery") or [], [item])
    if merged == list(data.get("discovery") or []):
        return False
    data["discovery"] = merged
    return True


def backfill_known_devices(data: dict, *, pairing: list | None = None) -> bool:
    """Ensure selected / session / paired UDIDs stay in the persisted discovery list."""
    extras: list[dict] = []
    selected = data.get("selected") if isinstance(data.get("selected"), dict) else {}
    if selected.get("udid"):
        extras.append(
            {
                "udid": selected["udid"],
                "transport": selected.get("transport") or "mobdev2",
                "host": selected.get("host"),
                "name": selected.get("name"),
                "product_version": selected.get("product_version"),
                "connection": selected.get("connection") or "wifi",
                "source": "selected",
            }
        )
    for udid, session in _sessions_map(data).items():
        if not isinstance(session, dict):
            continue
        extras.append(
            {
                "udid": udid,
                "transport": session.get("transport") or selected.get("transport") or "mobdev2",
                "host": session.get("host") if "host" in session else selected.get("host"),
                "name": session.get("name"),
                "product_version": session.get("product_version"),
                "connection": session.get("connection") or "wifi",
                "source": "session",
            }
        )
    for item in pairing or []:
        if not isinstance(item, dict) or not item.get("udid") or item.get("system_configuration"):
            continue
        extras.append(
            {
                "udid": item["udid"],
                "connection": "wifi",
                "name": item.get("device_name") or item.get("name"),
                "product_version": item.get("product_version"),
                "source": "pairing",
            }
        )
    if not extras:
        return False
    merged, added = merge_known_devices(data.get("discovery") or [], extras)
    if merged == list(data.get("discovery") or []):
        return False
    data["discovery"] = merged
    return True


def refresh_devices(store: StateStore, binary: str, *, timeout: float) -> Outcome:
    report = discover(binary, timeout=timeout)
    data = store.load()
    previous = [item for item in (data.get("discovery") or []) if isinstance(item, dict) and item.get("udid")]
    merged, added = merge_known_devices(previous, report["devices"])
    data["discovery"] = merged
    remember_device_metadata(data, merged, data.get("selected"))
    store.save(data)
    wifi = [item for item in report["devices"] if item.get("connection") == "wifi"]
    usb = [item for item in report["devices"] if item.get("connection") == "usb"]
    if added:
        summary = f"新检测到 {len(added)} 台设备，已加入列表。当前共 {len(merged)} 台。本次看到 Wi-Fi {len(wifi)} 台、USB {len(usb)} 台。"
    else:
        summary = f"没有发现新设备，已刷新现有列表。当前共 {len(merged)} 台。本次看到 Wi-Fi {len(wifi)} 台、USB {len(usb)} 台。"
    details = dict(report)
    details["added"] = added
    details["added_count"] = len(added)
    details["known_count"] = len(merged)
    return Outcome(True, "LISTED", 0, summary, details)


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
    record_name = (record or {}).get("name") if record else None
    record_version = (record or {}).get("product_version") if record else None
    data["selected"] = {
        "udid": target.udid,
        "transport": target.transport,
        "host": target.host,
        "usbmux_address": target.usbmux_address,
        "name": display or record_name,
        "product_version": record_version,
        "connection": connection,
    }
    remember_device_metadata(data, data["selected"], record)
    remember_known_device(data, data["selected"])
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
    with store.transaction() as data:
        data["last_command"] = {
            "accepted": outcome.ok and outcome.code in {"SET_HOLDING", "SET_RETURNED", "CLEARED"},
            "code": outcome.code,
            "summary": outcome.summary,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
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


def desired_targets_map(data: dict) -> dict:
    targets = data.get("desired_targets")
    if not isinstance(targets, dict):
        targets = {}
        data["desired_targets"] = targets
    return targets


def _target_coords(item: dict) -> tuple[str | None, str | None]:
    lat = item.get("lat", item.get("latitude"))
    lon = item.get("lon", item.get("longitude"))
    if lat is None or lon is None:
        return None, None
    return str(lat), str(lon)


def remember_desired_target(
    store: StateStore,
    *,
    udid: str,
    lat: str,
    lon: str,
    profile: str,
    transport: str | None = None,
    host: str | None = None,
) -> dict:
    with store.transaction() as data:
        selected = data.get("selected") if isinstance(data.get("selected"), dict) else {}
        targets = desired_targets_map(data)
        record = {
            "udid": udid,
            "lat": str(lat),
            "lon": str(lon),
            "latitude": str(lat),
            "longitude": str(lon),
            "profile": profile,
            "transport": transport or selected.get("transport"),
            "host": host if host is not None else selected.get("host"),
            "enabled": True,
        }
        targets[udid] = record
        data["desired_targets"] = targets
        return dict(record)


def desired_target_active(data: dict, udid: str | None) -> bool:
    """True only when auto-restore should keep (re)starting a holder for this UDID."""
    if not udid:
        return False
    item = desired_targets_map(data).get(udid)
    if not isinstance(item, dict) or item.get("enabled") is False or item.get("cleared"):
        return False
    lat, lon = _target_coords(item)
    return bool(lat and lon)


def _forget_desired_in_data(data: dict, udid: str) -> None:
    targets = desired_targets_map(data)
    targets[udid] = {"udid": udid, "enabled": False, "cleared": True, "lat": None, "lon": None}
    data["desired_targets"] = targets
    session = _session_for(data, udid)
    if session:
        session = dict(session)
        session["desired"] = False
        session["latitude"] = None
        session["longitude"] = None
        session["holding"] = False
        session["pid"] = None
        session["watchdog_pid"] = None
        session["child_pid"] = None
        session["watchdog_active"] = False
        _put_session(data, udid, session)


def forget_desired_target(store: StateStore, udid: str | None) -> None:
    if not udid:
        return
    with store.transaction() as data:
        _forget_desired_in_data(data, udid)


def backfill_desired_targets(data: dict) -> dict:
    """Promote leftover session coordinates so an upgrade keeps auto-resume."""
    targets = desired_targets_map(data)
    selected = data.get("selected") if isinstance(data.get("selected"), dict) else {}
    changed = False
    for udid, session in _sessions_map(data).items():
        if not isinstance(session, dict) or udid in targets:
            continue
        lat, lon = _target_coords(session)
        if not lat or not lon:
            continue
        targets[udid] = {
            "udid": udid,
            "lat": lat,
            "lon": lon,
            "latitude": lat,
            "longitude": lon,
            "profile": session.get("profile") or "ios17",
            "transport": session.get("transport") or selected.get("transport"),
            "host": session.get("host") if "host" in session else selected.get("host"),
            "enabled": True,
        }
        changed = True
    data["desired_targets"] = targets
    return data if changed or targets else data


def list_enabled_desired_targets(data: dict) -> list[dict]:
    backfill_desired_targets(data)
    items = []
    for udid, item in desired_targets_map(data).items():
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        lat, lon = _target_coords(item)
        if not lat or not lon:
            continue
        row = dict(item)
        row["udid"] = udid
        row["lat"] = lat
        row["lon"] = lon
        row["latitude"] = lat
        row["longitude"] = lon
        row["enabled"] = True
        items.append(row)
    return items


def auto_restore_enabled() -> bool:
    return os.environ.get("IOS_WIFI_LOC_NO_AUTORESTORE", "").strip().lower() not in {"1", "true", "yes"}


_RESUME_LOCK = threading.Lock()
_UDID_THREAD_LOCKS: dict[str, threading.RLock] = {}
_UDID_THREAD_GUARD = threading.Lock()
_LOCK_STATE = threading.local()


def _safe_udid_token(udid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in udid)


def _thread_lock_for_udid(udid: str) -> threading.RLock:
    with _UDID_THREAD_GUARD:
        lock = _UDID_THREAD_LOCKS.get(udid)
        if lock is None:
            lock = threading.RLock()
            _UDID_THREAD_LOCKS[udid] = lock
        return lock


@contextmanager
def hold_spawn_lock(store: StateStore, udid: str):
    """Serialize starting/stopping _hold for one UDID (reentrant thread + fcntl file lock)."""
    thread_lock = _thread_lock_for_udid(udid)
    thread_lock.acquire()
    owned = getattr(_LOCK_STATE, "owned", None)
    if owned is None:
        owned = set()
        _LOCK_STATE.owned = owned
        _LOCK_STATE.handles = {}
    outermost = udid not in owned
    handle = None
    try:
        if outermost:
            owned.add(udid)
            path = store.directory / f"hold.{_safe_udid_token(udid)}.lock"
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            handle = open(path, "a+", encoding="utf-8")
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            _LOCK_STATE.handles[udid] = handle
        yield
    finally:
        if outermost:
            handle = _LOCK_STATE.handles.pop(udid, handle)
            if handle is not None:
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
                try:
                    handle.close()
                except OSError:
                    pass
            owned.discard(udid)
        thread_lock.release()


def _known_udids(data: dict) -> list[str]:
    found: list[str] = []
    def _add(value: object) -> None:
        if not isinstance(value, str) or not value or value in found:
            return
        try:
            found.append(validate_udid(value))
        except IdentifierError:
            found.append(value)

    selected = data.get("selected") if isinstance(data.get("selected"), dict) else {}
    _add(selected.get("udid"))
    for udid in (_sessions_map(data) or {}):
        _add(udid)
    for udid in desired_targets_map(data):
        _add(udid)
    for item in data.get("discovery") or []:
        if isinstance(item, dict):
            _add(item.get("udid"))
    return found


def reap_stray_holders(store: StateStore, udid: str | None = None, *, timeout: float = 5) -> dict:
    """Stop leftover _hold / simulate-location processes for one or all known UDIDs."""
    data = store.load()
    targets = [udid] if udid else _known_udids(data)
    pids: list[int] = []
    if udid:
        pids.extend(pids_matching(udid=udid, holders=True))
        session = _session_for(data, udid) or {}
        for key in ("pid", "watchdog_pid", "child_pid"):
            value = session.get(key)
            if isinstance(value, int) and value > 1:
                pids.append(value)
    else:
        pids.extend(pids_matching(state_dir=store.directory, holders=True))
        for item in targets:
            pids.extend(pids_matching(udid=item, holders=True))
        for session in _sessions_map(data).values():
            if not isinstance(session, dict):
                continue
            for key in ("pid", "watchdog_pid", "child_pid"):
                value = session.get(key)
                if isinstance(value, int) and value > 1:
                    pids.append(value)
    if udid:
        try:
            from ios_wifi_loc.watchdog import request_stop

            request_stop(store, udid)
        except Exception:
            pass
    else:
        try:
            from ios_wifi_loc.watchdog import request_stop

            for item in targets:
                request_stop(store, item)
        except Exception:
            pass
    result = terminate_pids(pids, timeout=timeout)
    # Clear stale PIDs in state for UDIDs we touched.
    touched = targets or []
    with store.transaction() as payload:
        for item in touched:
            session = _session_for(payload, item)
            if not session:
                continue
            session = dict(session)
            session["pid"] = None
            session["watchdog_pid"] = None
            session["child_pid"] = None
            session["holding"] = False
            session["watchdog_active"] = False
            session["waiting_reconnect"] = False
            session["waiting_for_wifi"] = False
            _put_session(payload, item, session)
    return result


def stop_all_holders(store: StateStore, *, timeout: float = 5) -> dict:
    return reap_stray_holders(store, None, timeout=timeout)


def resume_desired_targets(
    store: StateStore,
    binary: str,
    *,
    timeout: float = 20,
    grace: float = 2,
    allow_usb: bool = True,
    allow_legacy: bool = False,
    apply=None,
    holding=None,
) -> list[dict]:
    """Relaunch holders for every enabled saved target that is not already holding.

    `apply` and `holding` are injectable so unit tests can stay process-free.
    When `apply` is omitted, this is a no-op if auto-restore is disabled.
    """
    if apply is None and not auto_restore_enabled():
        return []
    if not _RESUME_LOCK.acquire(blocking=False):
        return []
    try:
        data = store.load()
        data = _release_stale_holder(store, data)
        backfill_desired_targets(data)
        store.save(data)
        previous = dict(data["selected"]) if isinstance(data.get("selected"), dict) else None
        results: list[dict] = []
        for item in list_enabled_desired_targets(data):
            udid = item["udid"]
            session = _session_for(data, udid) or {}
            pid = session.get("pid")
            is_holding = False
            counts = holder_process_counts(udid=udid)
            if holding is not None:
                is_holding = bool(holding(item, session))
            elif isinstance(pid, int) and pid > 1:
                is_holding = holder_matches(pid)
            else:
                is_holding = counts.watchdog_count == 1
            # A healthy iOS 17+ session is `_hold` + `_simulate` (or
            # `simulate-location set`): pids_matching(..., holders=True)
            # returns 2, which must not be treated as a duplicate.
            duplicate = counts.watchdog_count > 1 or counts.simulate_count > 1
            orphan_simulate = counts.watchdog_count == 0 and counts.simulate_count >= 1
            if counts.is_healthy_family() or (is_holding and not duplicate and not orphan_simulate):
                results.append({"udid": udid, "action": "already_holding", "ok": True, "lat": item["lat"], "lon": item["lon"]})
                continue
            with hold_spawn_lock(store, udid):
                data = store.load()
                if not desired_target_active(data, udid):
                    results.append({"udid": udid, "action": "skipped", "ok": True, "code": "NOT_DESIRED", "lat": item["lat"], "lon": item["lon"]})
                    continue
                if apply is not None:
                    outcome = apply(item)
                    ok = True if outcome is None else bool(getattr(outcome, "ok", outcome))
                    results.append({"udid": udid, "action": "resumed", "ok": ok, "lat": item["lat"], "lon": item["lon"]})
                    data = store.load()
                    continue
                selected = select_device(
                    store,
                    udid=udid,
                    transport=item.get("transport") or "mobdev2",
                    host=item.get("host"),
                    name=None,
                    allow_usb=allow_usb,
                    usbmux_address=None,
                )
                if not selected.ok:
                    results.append({"udid": udid, "action": "select_failed", "ok": False, "error": selected.summary})
                    continue
                outcome = set_location(
                    store,
                    binary,
                    latitude=item["lat"],
                    longitude=item["lon"],
                    profile=item.get("profile") or "ios17",
                    timeout=timeout,
                    grace=grace,
                    foreground=False,
                    allow_usb=allow_usb,
                    allow_legacy=allow_legacy,
                    replace=True,
                    only_if_desired=True,
                )
            results.append(
                {
                    "udid": udid,
                    "action": "resumed" if outcome.ok else "failed",
                    "ok": outcome.ok,
                    "code": outcome.code,
                    "summary": outcome.summary,
                    "lat": item["lat"],
                    "lon": item["lon"],
                }
            )
            data = store.load()
        if previous is not None:
            data = store.load()
            data["selected"] = previous
            _sync_legacy_session(data)
            store.save(data)
        return results
    finally:
        _RESUME_LOCK.release()


def _target_is_holding(item: dict, session: dict | None, holding=None) -> bool:
    session = session or {}
    if holding is not None:
        return bool(holding(item, session))
    pid = session.get("pid")
    return bool(isinstance(pid, int) and pid > 1 and holder_matches(pid))


def pending_desired_targets(store: StateStore, *, holding=None) -> list[dict]:
    data = store.load()
    pending: list[dict] = []
    for item in list_enabled_desired_targets(data):
        if not _target_is_holding(item, _session_for(data, item["udid"]), holding=holding):
            pending.append(item)
    return pending


def restore_interval() -> float:
    raw = os.environ.get("IOS_WIFI_LOC_RESTORE_INTERVAL", "2")
    try:
        return max(0.05, min(30.0, float(raw)))
    except ValueError:
        return 2.0


def restore_desired_loop(
    stop,
    store: StateStore,
    binary: str,
    *,
    timeout: float = 20,
    grace: float = 2,
    interval: float | None = None,
    apply=None,
    holding=None,
) -> list[dict]:
    """Keep retrying saved coordinates until each UDID is holding again.

    Intended as a serve() background thread: it waits for tunneld / the phone
    to reappear instead of giving up on the first failed start-up attempt.
    """
    delay = restore_interval() if interval is None else max(0.05, interval)
    last: list[dict] = []
    wait = getattr(stop, "wait", None)
    is_set = getattr(stop, "is_set", lambda: False)
    while not is_set():
        try:
            last = resume_desired_targets(
                store,
                binary,
                timeout=timeout,
                grace=grace,
                apply=apply,
                holding=holding,
            )
        except Exception:
            pass
        pending = pending_desired_targets(store, holding=holding)
        sleep_for = delay if pending else max(delay, 8.0)
        if wait is not None:
            if wait(sleep_for):
                break
        else:
            break
    return last


def _sync_legacy_session(data: dict) -> None:
    selected = data.get("selected") or {}
    udid = selected.get("udid") if isinstance(selected, dict) else None
    sessions = _sessions_map(data)
    data["session"] = sessions.get(udid) if udid else data.get("session")


GENERIC_DEVICE_NAMES = {"iphone", "ipad", "ipod", "ipod touch", "apple"}


def is_generic_device_name(name: object) -> bool:
    text = str(name or "").strip()
    return (not text) or text.casefold() in GENERIC_DEVICE_NAMES


def preferred_device_name(*candidates: object) -> str | None:
    specific: list[str] = []
    generic: list[str] = []
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        if is_generic_device_name(text):
            if text not in generic:
                generic.append(text)
        elif text not in specific:
            specific.append(text)
    if specific:
        return specific[0]
    return generic[0] if generic else None


def preferred_product_version(*candidates: object) -> str | None:
    for raw in candidates:
        text = str(raw or "").strip()
        if text:
            return text
    return None


def apply_device_metadata(item: dict, names: dict | None = None, *extra_sources: object) -> dict:
    """Fill name / iOS version from cache and related records without inventing data."""
    out = dict(item)
    udid = out.get("udid")
    cached = (names or {}).get(udid) if isinstance(names, dict) and udid else None
    cached = cached if isinstance(cached, dict) else {}
    name_candidates = [out.get("name"), out.get("device_name"), cached.get("name")]
    version_candidates = [out.get("product_version"), out.get("ios_version"), cached.get("product_version")]
    for source in extra_sources:
        if not isinstance(source, dict):
            continue
        if source.get("udid") and udid and source.get("udid") != udid:
            continue
        name_candidates.append(source.get("name") or source.get("device_name"))
        version_candidates.append(source.get("product_version") or source.get("ios_version"))
    name = preferred_device_name(*name_candidates)
    if name:
        out["name"] = name
    version = preferred_product_version(*version_candidates)
    if version:
        out["product_version"] = version
    return out


def _device_names_map(data: dict) -> dict:
    names = data.get("device_names")
    if not isinstance(names, dict):
        names = {}
        data["device_names"] = names
    return names


def remember_device_metadata(data: dict, *sources: object) -> dict:
    names = _device_names_map(data)
    for source in sources:
        items = source
        if isinstance(source, dict) and "udid" in source:
            items = [source]
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or not item.get("udid"):
                continue
            udid = item["udid"]
            entry = dict(names.get(udid) or {})
            incoming = item.get("name") or item.get("device_name")
            if incoming:
                # A later generic "iPhone" from tunneld must not erase a saved friendly name.
                if not is_generic_device_name(incoming):
                    entry["name"] = preferred_device_name(incoming, entry.get("name")) or incoming
                else:
                    kept = preferred_device_name(entry.get("name"), incoming)
                    if kept:
                        entry["name"] = kept
            version = item.get("product_version") or item.get("ios_version")
            if version:
                entry["product_version"] = version
            if entry:
                names[udid] = entry
    data["device_names"] = names
    return names


def _release_stale_holder(store: StateStore, data: dict) -> dict:
    sessions = _sessions_map(data)
    changed = False
    for udid, session in list(sessions.items()):
        if not session or not session.get("pid"):
            continue
        pid = int(session["pid"])
        if holder_matches(pid):
            continue
        child = session.get("child_pid")
        if isinstance(child, int) and child > 1 and pid_alive(child):
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        session = dict(session)
        session["pid"] = None
        session["child_pid"] = None
        session["holding"] = False
        session["watchdog_active"] = False
        session["waiting_reconnect"] = False
        session["waiting_for_wifi"] = False
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
    replace: bool = False,
    only_if_desired: bool = False,
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
    with hold_spawn_lock(store, target.udid):
        outcome = _apply_location_locked(
            store,
            binary,
            target=target,
            latitude=lat,
            longitude=lon,
            profile=profile,
            timeout=timeout,
            grace=grace,
            foreground=foreground,
            allow_usb=allow_usb,
            allow_legacy=allow_legacy,
            usbmux_address=usbmux_address,
            replace=replace,
            only_if_desired=only_if_desired,
        )
        # Remember under the same lock. Resume (only_if_desired) never rewrites
        # desired_targets, so a concurrent clear cannot be undone after spawn.
        if outcome.ok and outcome.code != "NOT_DESIRED" and not only_if_desired:
            udid = (outcome.details or {}).get("udid") or target.udid
            remember_desired_target(
                store,
                udid=str(udid),
                lat=str((outcome.details or {}).get("latitude") or lat),
                lon=str((outcome.details or {}).get("longitude") or lon),
                profile=str((outcome.details or {}).get("profile") or profile),
            )
        return outcome


def _apply_location_locked(
    store: StateStore,
    binary: str,
    *,
    target: Target,
    latitude: str,
    longitude: str,
    profile: str,
    timeout: float,
    grace: float,
    foreground: bool,
    allow_usb: bool,
    allow_legacy: bool,
    usbmux_address: str | None,
    replace: bool,
    only_if_desired: bool = False,
) -> Outcome:
    lat, lon = latitude, longitude
    data = _release_stale_holder(store, store.load())
    if only_if_desired and not desired_target_active(data, target.udid):
        return Outcome(
            True,
            "NOT_DESIRED",
            0,
            "该设备已恢复真实定位，不再自动下发。",
            {"udid": target.udid},
        )
    session = _session_for(data, target.udid) or {}
    live = pids_matching(udid=target.udid, holders=True)
    recorded = session.get("pid")
    has_live = bool(live) or (isinstance(recorded, int) and recorded > 1 and holder_matches(recorded))
    if has_live and not replace:
        return _fail("DUPLICATE_SESSION", 4, "该设备已有定位会话进程。先清除它，再发送新坐标。不会启动第二个会话。其它手机的模拟不受影响。")
    # Always drop previous holders for this UDID before a replace/new start,
    # including orphans that are no longer recorded in state.json.
    reap_stray_holders(store, target.udid, timeout=min(timeout, 5))
    data = _release_stale_holder(store, store.load())
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
    from ios_wifi_loc.watchdog import clear_stop, hold_command_argv

    log_out, log_err = _session_logs(store, target.udid)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in target.udid)
    hold_out = store.directory / f"hold.{safe}.stdout"
    hold_err = store.directory / f"hold.{safe}.stderr"
    clear_stop(store, target.udid)
    use_tunnel = "--tunnel" in argv
    hold_argv = hold_command_argv(
        sys.executable,
        store,
        binary,
        target,
        lat,
        lon,
        command_profile,
        grace,
        use_tunnel=use_tunnel,
    )
    try:
        proc = spawn(hold_argv, stdout_path=hold_out, stderr_path=hold_err)
    except FileNotFoundError:
        return _fail("BINARY_MISSING", 7, "找不到上游可执行文件")
    except OSError as exc:
        return _fail("UPSTREAM_FAILED", 4, f"上游进程没有启动：{exc.errno}")
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    if proc.poll() is not None:
        tail = _read_tail(log_err) or _read_tail(hold_err)
        if proc.returncode in {0, 4}:
            return _fail(
                "SESSION_ENDED_EARLY",
                4,
                "iOS 17+ 的上游 set 按文档应保持到被中断，但进程已经提前退出。不能确认定位仍在模拟。",
                stderr=tail,
            )
        return _fail("UPSTREAM_FAILED", 4, f"上游 set 失败，退出码 {proc.returncode}。", stderr=tail)
    with store.transaction() as data:
        current = _session_for(data, target.udid) or {}
        try:
            reconnect_count = int(current.get("reconnect_count") or 0)
        except (TypeError, ValueError):
            reconnect_count = 0
        record = {
            "pid": proc.pid,
            "watchdog_pid": proc.pid,
            "child_pid": current.get("child_pid"),
            "profile": "ios17",
            "udid": target.udid,
            "latitude": lat,
            "longitude": lon,
            "argv": argv[1:],
            "started_at": current.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "holding": True,
            "watchdog_active": True,
            "reconnect_count": reconnect_count,
            "last_reconnect_at": current.get("last_reconnect_at"),
            "last_error": current.get("last_error"),
            "waiting_reconnect": bool(current.get("waiting_reconnect")),
        }
        _put_session(data, target.udid, record)
    if not foreground:
        return Outcome(
            True,
            "SET_HOLDING",
            0,
            "上游 set 进程仍在运行。这只说明本机进程还在；按上游文档，iOS 17+ 的模拟由该进程保持。手机是否接受坐标需要真机确认。其它已在模拟的手机不会被打断。自动重连已开启，隧道断开后会按原坐标重新发起。",
            {
                "pid": proc.pid,
                "profile": "ios17",
                "latitude": lat,
                "longitude": lon,
                "udid": target.udid,
                "watchdog_active": True,
                "reconnect_count": reconnect_count,
            },
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
    replace: bool = False,
    only_if_desired: bool = False,
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
            replace=replace,
            only_if_desired=only_if_desired,
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


def stop_holder_for_udid(store: StateStore, udid: str | None, *, timeout: float) -> dict:
    data = store.load()
    session = _session_for(data, udid) if udid else (data.get("session") or None)
    holder = {"signaled": False, "exited": True, "reason": "not_running"}
    if udid:
        from ios_wifi_loc.watchdog import request_stop

        request_stop(store, udid)
    pids = []
    if session:
        for key in ("pid", "watchdog_pid", "child_pid"):
            value = session.get(key)
            if isinstance(value, int) and value > 1 and value not in pids:
                pids.append(value)
    if udid:
        pids.extend(pids_matching(udid=udid, holders=True))
    if pids:
        holder = terminate_pids(pids, timeout=min(timeout, 5))
        holder = {
            "signaled": bool(holder.get("signaled")),
            "exited": not holder.get("remaining"),
            "reason": "exited" if not holder.get("remaining") else "unconfirmed",
            "pids": holder.get("pids") or pids,
        }
        if udid:
            current = _session_for(data, udid)
            if current:
                current = dict(current)
                current["pid"] = None
                current["child_pid"] = None
                current["holding"] = False
                current["watchdog_active"] = False
                current["waiting_reconnect"] = False
                current["waiting_for_wifi"] = False
                _put_session(data, udid, current)
                store.save(data)
    return holder


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
    holder = stop_holder_for_udid(store, udid, timeout=timeout)
    data = store.load()
    session = _session_for(data, udid) if udid else (data.get("session") or None)
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
    data = store.load()
    try:
        udid = _selected_target(data).udid
    except (PlanError, IdentifierError):
        selected = data.get("selected") if isinstance(data.get("selected"), dict) else {}
        udid = selected.get("udid")
    if not udid:
        return _remember(store, _clear_location(store, binary, timeout=timeout, allow_usb=allow_usb, profile=profile))
    # Forget desired_targets *before* stopping the holder, under the same
    # per-UDID lock that resume/set_location uses, so restore_desired_loop
    # cannot respawn a new _hold while clear is still running.
    with hold_spawn_lock(store, udid):
        forget_desired_target(store, udid)
        outcome = _remember(store, _clear_location(store, binary, timeout=timeout, allow_usb=allow_usb, profile=profile))
        forget_desired_target(store, udid)
        return outcome


def _public_sessions(data: dict) -> list[dict]:
    items = []
    for udid, session in _sessions_map(data).items():
        if not isinstance(session, dict):
            continue
        item = dict(session)
        item["udid"] = udid
        item["alive"] = bool(session.get("pid") and holder_matches(int(session["pid"])))
        item["session_alive"] = item["alive"]
        item["watchdog_active"] = bool(session.get("watchdog_active") and item["alive"])
        try:
            item["reconnect_count"] = int(session.get("reconnect_count") or 0)
        except (TypeError, ValueError):
            item["reconnect_count"] = 0
        item["waiting_reconnect"] = bool(session.get("waiting_reconnect") or (item["watchdog_active"] and not session.get("holding")))
        item["waiting_for_wifi"] = bool(session.get("waiting_for_wifi"))
        item["tunnel_address"] = session.get("tunnel_address")
        item["tunnel_port"] = session.get("tunnel_port")
        items.append(item)
    return items


def status(store: StateStore) -> Outcome:
    data = store.load()
    data = _release_stale_holder(store, data)
    if backfill_desired_targets(data) is not None:
        store.save(data)
    sessions = _public_sessions(data)
    desired = list_enabled_desired_targets(data)
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
            "desired_targets": desired,
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
        merged, _added = merge_known_devices(data.get("discovery") or [], report["devices"])
        data["discovery"] = merged
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
