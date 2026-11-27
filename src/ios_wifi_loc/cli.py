from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ios_wifi_loc import __version__
from ios_wifi_loc.doctor import collect_doctor
from ios_wifi_loc.guide import pair_guide
from ios_wifi_loc.session import (
    Outcome,
    clear_location,
    clear_selection,
    reconnect,
    refresh_devices,
    select_device,
    set_location,
    smoke,
    status,
)
from ios_wifi_loc.binary import DEFAULT_BINARY_NAME, resolve_binary
from ios_wifi_loc.install import default_state_dir_for_root, install_files, preflight, uninstall_files
from ios_wifi_loc.service import ServiceError, serve
from ios_wifi_loc.state import StateError, StateStore


def default_state_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "ios-wifi-loc"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ios-wifi-loc",
        description="通过 pymobiledevice3 控制 iPhone 的 Wi-Fi 开发者定位模拟。不修改路由，不配对，不读取配对秘密。",
    )
    parser.add_argument("--state-dir", default=None, help="本机状态目录，默认 ~/.local/share/ios-wifi-loc")
    parser.add_argument("--binary", default="pymobiledevice3", help="上游可执行文件")
    parser.add_argument("--json", action="store_true", help="向标准输出打印一个 JSON 对象")
    parser.add_argument("--timeout", type=float, default=20, help="单次上游调用超时（秒），最大 120")
    parser.add_argument("--version", action="store_true", help="打印本工具版本")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("version", help="打印本工具版本")
    sub.add_parser("doctor", help="诊断本机架构、上游命令和局域网接口")
    sub.add_parser("pair-guide", help="打印一次性 USB 配对说明，不连接设备")
    sub.add_parser("devices", help="列出 usbmux 看到的 Wi-Fi 与 USB 设备")
    sub.add_parser("discover", help="探测 usbmux、bonjour 和 remote browse，不改定位")
    sub.add_parser("status", help="查看本机记录的选择和持有进程")
    sub.add_parser("unselect", help="忘掉本机记录的设备选择")
    preflight_cmd = sub.add_parser("preflight", help="安装前检查")
    preflight_cmd.add_argument("--root", default="/")

    serve_cmd = sub.add_parser("serve", help="启动本机网页控制台")
    serve_cmd.add_argument("--interface", default=None, help="只绑定这块网卡的 IPv4；不指定则只监听 127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=47321)
    serve_cmd.add_argument("--no-watch", action="store_true")
    serve_cmd.add_argument("--watch-interval", type=float, default=10)
    auth = serve_cmd.add_mutually_exclusive_group()
    auth.add_argument("--no-auth", action="store_true", default=None, help="局域网免密打开页面（默认）")
    auth.add_argument("--require-auth", action="store_true", help="需要本机口令才能操作")

    install_cmd = sub.add_parser("install", help="安装到指定根目录，可逆")
    install_cmd.add_argument("--root", default="/")
    install_cmd.add_argument("--state-dir", default=argparse.SUPPRESS)
    install_cmd.add_argument("--interface", default=None, help="服务只绑定这块网卡；不指定则只监听 127.0.0.1")
    install_cmd.add_argument("--python", default=None, help="启动脚本里使用的 Python")
    install_cmd.add_argument("--require-auth", action="store_true", help="服务需要口令；默认免密，仅供受信局域网")
    uninstall_cmd = sub.add_parser("uninstall", help="删除启动脚本")
    uninstall_cmd.add_argument("--root", default="/")
    uninstall_cmd.add_argument("--state-dir", default=argparse.SUPPRESS)
    uninstall_cmd.add_argument("--purge-state", action="store_true")

    select = sub.add_parser("select", help="显式选择一台设备")
    select.add_argument("--udid", required=True)
    select.add_argument("--transport", choices=["usbmux", "mobdev2", "remotepairing"])
    select.add_argument("--host", default=None)
    select.add_argument("--name", default=None)
    select.add_argument("--allow-usb", action="store_true")
    select.add_argument("--usbmux-address", default=None)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--allow-usb", action="store_true")
    common.add_argument("--profile", choices=["auto", "pre17", "ios17"], default="auto")
    common.add_argument("--allow-legacy-ios17", action="store_true")
    common.add_argument("--startup-grace", type=float, default=5)

    set_cmd = sub.add_parser("set", parents=[common], help="设置经纬度")
    set_cmd.add_argument("--latitude", required=True)
    set_cmd.add_argument("--longitude", required=True)
    set_cmd.add_argument("--foreground", action="store_true")
    set_cmd.add_argument("--replace", action="store_true", help="若该设备已在模拟，先停止再改到新坐标")

    clear_cmd = sub.add_parser("clear", help="清除模拟定位")
    clear_cmd.add_argument("--allow-usb", action="store_true")
    clear_cmd.add_argument("--profile", choices=["auto", "pre17", "ios17"], default=None)

    again = sub.add_parser("reconnect", parents=[common], help="有限次重探所选 Wi-Fi 设备")
    again.add_argument("--attempts", type=int, default=3)
    again.add_argument("--pause", type=float, default=0.5)
    again.add_argument("--resume", action="store_true")
    again.add_argument("--latitude")
    again.add_argument("--longitude")

    smoke_cmd = sub.add_parser("smoke", parents=[common], help="真机冒烟。默认只演练，不改坐标")
    smoke_cmd.add_argument("--latitude", required=True)
    smoke_cmd.add_argument("--longitude", required=True)
    smoke_cmd.add_argument("--execute", action="store_true")
    smoke_cmd.add_argument("--i-understand-this-sets-a-real-device", action="store_true")

    hold = sub.add_parser("_hold", help=argparse.SUPPRESS)
    hold.add_argument("--udid", required=True)
    hold.add_argument("--transport", choices=["usbmux", "mobdev2", "remotepairing"], default="mobdev2")
    hold.add_argument("--host", default=None)
    hold.add_argument("--usbmux-address", default=None)
    hold.add_argument("--profile", choices=["pre17", "ios17"], default="ios17")
    hold.add_argument("--latitude", required=True)
    hold.add_argument("--longitude", required=True)
    hold.add_argument("--startup-grace", type=float, default=5)
    hold.add_argument("--use-tunnel", action="store_true")
    return parser


def _emit(outcome: Outcome, as_json: bool) -> int:
    payload = {
        "ok": outcome.ok,
        "code": outcome.code,
        "exit_code": outcome.exit_code,
        "summary": outcome.summary,
        "details": outcome.details,
    }
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(outcome.summary)
        argv = outcome.details.get("argv") if isinstance(outcome.details, dict) else None
        if isinstance(argv, list):
            print(" ".join(argv))
    return outcome.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.version and not args.cmd:
        print(__version__)
        return 0
    if args.cmd in {None, "version"} and not args.version:
        if args.cmd == "version":
            print(__version__)
            return 0
        parser.print_help()
        return 2
    if args.version and args.cmd == "version":
        print(__version__)
        return 0
    if args.timeout <= 0 or args.timeout > 120:
        return _emit(Outcome(False, "VALIDATION", 2, "超时必须大于 0 且不超过 120 秒。", {}), args.json)
    if args.binary == DEFAULT_BINARY_NAME:
        args.binary = resolve_binary(args.binary)
    try:
        store = StateStore(Path(args.state_dir) if args.state_dir else default_state_dir())
        if args.cmd == "doctor":
            report = collect_doctor(args.binary, timeout=args.timeout, probe=True)
            outcome = Outcome(True, "DOCTOR", 0, "诊断完成。下面的结论只属于这台计算机，不是真机定位测试。", report)
        elif args.cmd == "pair-guide":
            outcome = Outcome(True, "GUIDE", 0, pair_guide(), {})
        elif args.cmd in {"devices", "discover"}:
            outcome = refresh_devices(store, args.binary, timeout=args.timeout)
        elif args.cmd == "select":
            outcome = select_device(
                store,
                udid=args.udid,
                transport=args.transport,
                host=args.host,
                name=args.name,
                allow_usb=args.allow_usb,
                usbmux_address=args.usbmux_address,
            )
        elif args.cmd == "unselect":
            outcome = clear_selection(store)
        elif args.cmd == "status":
            outcome = status(store)
        elif args.cmd == "set":
            outcome = set_location(
                store,
                args.binary,
                latitude=args.latitude,
                longitude=args.longitude,
                profile=args.profile,
                timeout=args.timeout,
                grace=args.startup_grace,
                foreground=args.foreground,
                allow_usb=args.allow_usb,
                allow_legacy=args.allow_legacy_ios17,
                replace=bool(getattr(args, "replace", False)),
            )
        elif args.cmd == "clear":
            outcome = clear_location(
                store,
                args.binary,
                timeout=args.timeout,
                allow_usb=args.allow_usb,
                profile=args.profile,
            )
        elif args.cmd == "reconnect":
            outcome = reconnect(
                store,
                args.binary,
                attempts=args.attempts,
                timeout=args.timeout,
                pause=args.pause,
                resume=args.resume,
                latitude=args.latitude,
                longitude=args.longitude,
                profile=args.profile,
                grace=args.startup_grace,
                allow_usb=args.allow_usb,
                allow_legacy=args.allow_legacy_ios17,
            )
        elif args.cmd == "preflight":
            report = preflight(Path(args.root) if getattr(args, "root", None) else Path("/"))
            outcome = Outcome(True, "PREFLIGHT", 0, "安装前检查完成。警告不代表已经在该系统上跑通上游。", report)
        elif args.cmd == "serve":
            if args.port < 0 or args.port > 65535:
                return _emit(Outcome(False, "VALIDATION", 2, "端口无效", {}), args.json)
            try:
                require_auth = bool(args.require_auth)
                serve(
                    store,
                    args.binary,
                    interface=args.interface,
                    port=args.port,
                    timeout=args.timeout,
                    grace=args.startup_grace if hasattr(args, "startup_grace") else 2,
                    watch=not args.no_watch,
                    watch_interval=args.watch_interval,
                    require_auth=require_auth,
                )
            except ServiceError as exc:
                outcome = Outcome(False, "SERVICE", 2, str(exc), {})
            else:
                return 0
        elif args.cmd == "install":
            state_dir = Path(args.state_dir) if args.state_dir else default_state_dir_for_root(Path(args.root))
            try:
                report = install_files(
                    Path(args.root),
                    state_dir=state_dir,
                    executable=args.python,
                    interface=args.interface,
                    binary=args.binary,
                    require_auth=bool(getattr(args, "require_auth", False)),
                )
            except ValueError as exc:
                outcome = Outcome(False, "VALIDATION", 2, str(exc), {})
            else:
                outcome = Outcome(True, "INSTALLED", 0, "已安装。口令只在状态目录的 web.secret，不要把它写进日志。", report)
        elif args.cmd == "uninstall":
            state_dir = Path(args.state_dir) if args.state_dir else default_state_dir_for_root(Path(args.root))
            report = uninstall_files(Path(args.root), state_dir=state_dir, purge_state=args.purge_state)
            outcome = Outcome(True, "UNINSTALLED", 0, "已删除启动脚本。", report)
        elif args.cmd == "_hold":
            from ios_wifi_loc.watchdog import run_hold

            return run_hold(store, args)
        elif args.cmd == "smoke":
            outcome = smoke(
                store,
                args.binary,
                latitude=args.latitude,
                longitude=args.longitude,
                profile=args.profile,
                execute=args.execute,
                acknowledge=args.i_understand_this_sets_a_real_device,
                timeout=args.timeout,
                grace=args.startup_grace,
                allow_usb=args.allow_usb,
                allow_legacy=args.allow_legacy_ios17,
            )
        else:
            outcome = Outcome(False, "VALIDATION", 2, "未知命令", {})
    except StateError as exc:
        outcome = Outcome(False, "STATE", 4, str(exc), {})
    return _emit(outcome, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
