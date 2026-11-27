from __future__ import annotations

import platform
import shutil
from pathlib import Path

from ios_wifi_loc.runner import run
from ios_wifi_loc.upstream import help_argv, version_argv

HELP_PROBES = [
    (["version"], []),
    (["developer", "dvt", "simulate-location", "set"], ["latitude", "longitude"]),
    (["developer", "simulate-location", "set"], ["latitude", "longitude"]),
    (["developer", "dvt", "simulate-location", "clear"], []),
    (["usbmux", "list"], ["--network", "--simple"]),
    (["bonjour", "mobdev2"], []),
    (["remote", "browse"], ["--timeout"]),
    (["remote", "pair-host"], []),
    (["lockdown", "info"], []),
    (["lockdown", "wifi-connections"], []),
    (["lockdown", "remotepairing"], ["--pair"]),
]


def grade_host(*, openwrt_text: str | None, machine: str, mem_kb: int | None, upstream_help_ok: bool) -> dict:
    memory = None
    if mem_kb is not None and mem_kb < 256 * 1024:
        memory = "观察到的内存低于 256MB。没有在这个内存规模上完成上游安装，不承诺能运行。"
    if openwrt_text:
        openwrt = {
            "level": "help_ok_on_this_openwrt" if upstream_help_ok else "openwrt_seen_upstream_not_verified",
            "promised": False,
            "note": "只说明这台机器的根文件系统像 OpenWrt。没有据此承诺软件包、内存或真机可用。",
        }
    else:
        openwrt = {
            "level": "not_observed",
            "promised": False,
            "note": "本机没有 /etc/openwrt_release。不能据此声称 OpenWrt 可以运行本工具或 pymobiledevice3。",
        }
    return {
        "openwrt": openwrt,
        "low_memory": memory,
        "machine": machine,
        "aarch64_same_as_r4s_cpu_class": machine in {"aarch64", "arm64"},
        "xe300_128mb_mips": {
            "verdict": "not_promised",
            "note": "没有在 128MB、MIPS 的 GL.iNet XE300 上安装或运行。不承诺单机能运行。",
        },
        "physical_iphone": {
            "verdict": "not_attached",
            "note": "环境诊断不连接手机，也不能把命令帮助存在解释成定位模拟成功。",
        },
    }


def _mem_kb() -> int | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def _openwrt_text() -> str | None:
    path = Path("/etc/openwrt_release")
    if not path.exists():
        return None
    allowed = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("DISTRIB_ID=", "DISTRIB_RELEASE=", "DISTRIB_ARCH=", "DISTRIB_TARGET=")):
            allowed.append(line[:200])
    return "\n".join(allowed)


def _ipv4_ioctl(name: str) -> list[str]:
    try:
        import fcntl
        import socket
        import struct
    except ImportError:
        return []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packed = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", name.encode("ascii", "replace")[:15]))
    except OSError:
        return []
    return [socket.inet_ntoa(packed[20:24])]


def _sysfs_interfaces() -> list[dict]:
    root = Path("/sys/class/net")
    if not root.is_dir():
        return []
    rows = []
    for iface in sorted(item.name for item in root.iterdir()):
        if iface == "lo":
            continue
        oper_path = root / iface / "operstate"
        oper = oper_path.read_text(encoding="utf-8").strip() if oper_path.exists() else None
        rows.append({"name": iface, "operstate": oper, "inet": _ipv4_ioctl(iface)})
    return rows


def _interfaces() -> list[dict]:
    ip = shutil.which("ip")
    if not ip:
        return _sysfs_interfaces()
    result = run([ip, "-j", "address"], timeout=5)
    if not result.ok:
        return _sysfs_interfaces()
    import json

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _sysfs_interfaces()
    rows = []
    if not isinstance(payload, list):
        return _sysfs_interfaces()
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("ifname") or "")
        if name == "lo" or not name:
            continue
        addresses = []
        for addr in item.get("addr_info") or []:
            if isinstance(addr, dict) and addr.get("family") == "inet":
                local = addr.get("local")
                if isinstance(local, str):
                    addresses.append(local)
        rows.append({"name": name, "operstate": item.get("operstate"), "inet": addresses})
    return rows or _sysfs_interfaces()


def _usbmux_socket() -> bool:
    return any(Path(path).exists() for path in ("/var/run/usbmuxd", "/tmp/usbmuxd", "/var/run/usbmuxd.sock"))


def collect_doctor(binary: str, *, timeout: float, probe: bool) -> dict:
    machine = platform.machine()
    version_result = run(version_argv(binary), timeout=min(timeout, 20)) if probe else None
    help_rows = []
    if probe:
        for parts, markers in HELP_PROBES:
            if parts == ["version"]:
                continue
            result = run(help_argv(binary, parts), timeout=min(timeout, 40))
            text = result.stdout + "\n" + result.stderr
            help_rows.append(
                {
                    "argv": parts + ["--help"],
                    "returncode": result.returncode,
                    "timed_out": result.timed_out,
                    "error": result.error,
                    "markers_present": [marker for marker in markers if marker in text],
                    "markers_missing": [marker for marker in markers if marker not in text],
                }
            )
    dvt = next((row for row in help_rows if row["argv"][:4] == ["developer", "dvt", "simulate-location", "set"]), None)
    upstream_help_ok = bool(dvt and dvt["returncode"] == 0 and not dvt["markers_missing"] and dvt["error"] is None)
    openwrt = _openwrt_text()
    report = {
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": machine,
        "mem_kb": _mem_kb(),
        "openwrt_release": openwrt,
        "interfaces": _interfaces(),
        "usbmux_socket_present": _usbmux_socket(),
        "binary": binary,
        "binary_resolved": shutil.which(binary) if "/" not in binary else binary,
        "upstream_version": None if version_result is None else version_result.stdout.strip()[:200],
        "upstream_version_error": None if version_result is None else version_result.error,
        "upstream_version_returncode": None if version_result is None else version_result.returncode,
        "help": help_rows,
        "grade": grade_host(
            openwrt_text=openwrt,
            machine=machine,
            mem_kb=_mem_kb(),
            upstream_help_ok=upstream_help_ok,
        ),
        "limits": [
            "诊断结果只描述这台计算机和上游命令帮助。",
            "macOS 虚拟机里的 iOS Simulator 不能代替实物 iPhone，本工具不会启动 Simulator。",
            "没有修改路由、防火墙或任何手机设置。",
        ],
    }
    return report
