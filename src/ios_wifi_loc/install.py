from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
from pathlib import Path

from ios_wifi_loc.binary import infer_binary_from_python
from ios_wifi_loc.pairing import sync_lockdown
from ios_wifi_loc.service import DEFAULT_PORT, load_or_create_secret, secret_path

_INTERFACE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,14}$")


def validate_interface(name: str | None) -> str | None:
    if name is None or name == "":
        return None
    if name in {"0.0.0.0", "::", "::0"} or _INTERFACE.fullmatch(name) is None:
        raise ValueError("网卡名无效。局域网请写 --interface br-lan 这样的网卡名，不能写 0.0.0.0。")
    return name


def detect_init(root: Path) -> str:
    if (root / "etc/openwrt_release").exists():
        return "procd"
    if (root / "etc/alpine-release").exists():
        return "openrc"
    systemd = root / "usr/lib/systemd/system"
    if systemd.is_dir() or (root / "etc/systemd/system").is_dir():
        return "systemd"
    if (root / "sbin/openrc").exists() or (root / "sbin/openrc-run").exists() or (root / "etc/init.d/openrc").exists():
        return "openrc"
    return "none"


def default_state_dir_for_root(root: Path) -> Path:
    if detect_init(root) == "procd":
        return root / "etc/ios-wifi-loc"
    return root / "var/lib/ios-wifi-loc"


def migrate_openwrt_state(root: Path, state_dir: Path) -> list[str]:
    notes: list[str] = []
    old = root / "var/lib/ios-wifi-loc"
    try:
        if old.resolve() == state_dir.resolve():
            return notes
    except OSError:
        if old == state_dir:
            return notes
    if not old.is_dir():
        return notes
    state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(state_dir, 0o700)
    for name in ("web.secret", "state.json"):
        source = old / name
        destination = state_dir / name
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)
            os.chmod(destination, 0o600)
            notes.append(f"migrated {name}")
    old_lockdown = old / "lockdown"
    new_lockdown = state_dir / "lockdown"
    if old_lockdown.is_dir():
        new_lockdown.mkdir(parents=True, mode=0o700, exist_ok=True)
        for path in old_lockdown.glob("*.plist"):
            destination = new_lockdown / path.name
            if path.is_file() and not destination.exists():
                shutil.copy2(path, destination)
                os.chmod(destination, 0o600)
                notes.append(f"migrated lockdown/{path.name}")
    runtime = root / "var/lib/lockdown"
    if runtime.is_dir():
        sync = sync_lockdown(state_dir, runtime_dir=runtime, backup_runtime=True)
        if sync["copied_in"]:
            notes.append(f"backed_up_runtime_lockdown:{sync['copied_in']}")
    return notes


def preflight(root: Path) -> dict:
    mem_kb = None
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                mem_kb = int(line.split()[1])
                break
    warnings = []
    if mem_kb is not None and mem_kb < 256 * 1024:
        warnings.append("内存低于 256MB。控制台本身很小，但 pymobiledevice3 没有在这个内存上验证，不承诺能跑。")
    if detect_init(root) == "procd":
        warnings.append("检测到 OpenWrt。启动脚本只放 procd，不改防火墙、路由或 PassWall。软件包由 oneclick-install.sh 处理。状态目录默认是 /etc/ios-wifi-loc，因为 /var 在 OpenWrt 上通常是内存盘。")
    if platform.machine() not in {"aarch64", "arm64", "x86_64"}:
        warnings.append("当前架构不是已看过的 x86_64 或 aarch64。")
    return {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "mem_kb": mem_kb,
        "init": detect_init(root),
        "warnings": warnings,
        "hard_fail": False,
    }


def _normalize_port(port: int | None) -> int:
    value = DEFAULT_PORT if port is None else int(port)
    if value < 1 or value > 65535:
        raise ValueError("端口必须在 1 到 65535 之间")
    return value


def _serve_command(
    executable: str,
    state_dir: Path,
    interface: str | None,
    binary: str | None,
    *,
    require_auth: bool,
    port: int | None = None,
) -> str:
    parts = [executable, "-m", "ios_wifi_loc", "--state-dir", str(state_dir)]
    if binary:
        parts.extend(["--binary", binary])
    parts.append("serve")
    checked = validate_interface(interface)
    if checked:
        parts.extend(["--interface", checked])
    parts.extend(["--port", str(_normalize_port(port))])
    if require_auth:
        parts.append("--require-auth")
    else:
        parts.append("--no-auth")
    return " ".join(shlex.quote(part) for part in parts)


def _tunneld_command(binary: str) -> str:
    parts = [binary, "remote", "tunneld", "--protocol", "tcp", "--no-usb", "--no-usbmux", "--mobdev2"]
    return " ".join(shlex.quote(part) for part in parts)


def _procd_unit(executable: str, state_dir: Path, interface: str | None, binary: str, *, require_auth: bool, port: int | None = None) -> str:
    command = _serve_command(executable, state_dir, interface, binary, require_auth=require_auth, port=port)
    tunneld = _tunneld_command(binary)
    persist = shlex.quote(str(state_dir / "lockdown"))
    return (
        "#!/bin/sh /etc/rc.common\n"
        "START=99\n"
        "USE_PROCD=1\n"
        "\n"
        "sync_lockdown() {\n"
        f"\tmkdir -p {persist} /var/lib/lockdown\n"
        f"\tchmod 700 {persist} 2>/dev/null || true\n"
        "\tif [ -d /var/lib/lockdown ]; then\n"
        "\t\tfor f in /var/lib/lockdown/*.plist; do\n"
        "\t\t\t[ -f \"$f\" ] || continue\n"
        "\t\t\tbase=${f##*/}\n"
        "\t\t\tcase \"$base\" in\n"
        "\t\t\t*.plist) ;;\n"
        "\t\t\t*) continue ;;\n"
        "\t\t\tesac\n"
        f"\t\t\tif [ ! -f {persist}/\"$base\" ]; then\n"
        f"\t\t\t\tcp \"$f\" {persist}/\"$base\"\n"
        f"\t\t\t\tchmod 600 {persist}/\"$base\"\n"
        "\t\t\tfi\n"
        "\t\tdone\n"
        "\tfi\n"
        f"\tfor f in {persist}/*.plist; do\n"
        "\t\t[ -f \"$f\" ] || continue\n"
        "\t\tbase=${f##*/}\n"
        "\t\tcp \"$f\" /var/lib/lockdown/\"$base\"\n"
        "\t\tchmod 600 /var/lib/lockdown/\"$base\"\n"
        "\tdone\n"
        "}\n"
        "\n"
        "start_service() {\n"
        "\tsync_lockdown\n"
        "\tif [ -x /etc/init.d/usbmuxd ]; then\n"
        "\t\t/etc/init.d/usbmuxd restart >/dev/null 2>&1 || /etc/init.d/usbmuxd start >/dev/null 2>&1 || true\n"
        "\tfi\n"
        "\tprocd_open_instance tunneld\n"
        f"\tprocd_set_param command {tunneld}\n"
        "\tprocd_set_param respawn 3600 5 5\n"
        "\tprocd_close_instance\n"
        "\tprocd_open_instance\n"
        f"\tprocd_set_param command {command}\n"
        "\tprocd_set_param respawn 3600 5 5\n"
        "\tprocd_close_instance\n"
        "}\n"
    )


def _systemd_unit(executable: str, state_dir: Path, interface: str | None, binary: str | None, *, require_auth: bool, port: int | None = None) -> str:
    command = _serve_command(executable, state_dir, interface, binary, require_auth=require_auth, port=port)
    persist = shlex.quote(str(state_dir / "lockdown"))
    pre = (
        "/bin/sh -c "
        + shlex.quote(
            f"mkdir -p {state_dir / 'lockdown'} /var/lib/lockdown; "
            f"cp -a {state_dir / 'lockdown'}/*.plist /var/lib/lockdown/ 2>/dev/null || true"
        )
    )
    return (
        "[Unit]\n"
        "Description=iPhone Wi-Fi location console\n"
        "After=network.target ios-wifi-loc-tunneld.service\n"
        "Wants=ios-wifi-loc-tunneld.service\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStartPre={pre}\n"
        f"ExecStart={command}\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "StartLimitIntervalSec=300\n"
        "StartLimitBurst=5\n"
        "NoNewPrivileges=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _systemd_tunneld_unit(binary: str) -> str:
    command = _tunneld_command(binary)
    return (
        "[Unit]\n"
        "Description=pymobiledevice3 wireless tunneld for iOS 17+\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={command}\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "StartLimitIntervalSec=300\n"
        "StartLimitBurst=5\n"
        "NoNewPrivileges=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _openrc_unit(executable: str, state_dir: Path, interface: str | None, binary: str | None, *, require_auth: bool, port: int | None = None) -> str:
    command = _serve_command(executable, state_dir, interface, binary, require_auth=require_auth, port=port)
    persist = shlex.quote(str(state_dir / "lockdown"))
    return (
        "#!/sbin/openrc-run\n"
        "name=\"ios-wifi-loc\"\n"
        "command_background=yes\n"
        'pidfile="/run/ios-wifi-loc.pid"\n'
        "\n"
        "depend() {\n"
        "\tneed net\n"
        "\tuse avahi-daemon usbmuxd\n"
        "}\n"
        "\n"
        "start_pre() {\n"
        f"\tmkdir -p {persist} /var/lib/lockdown\n"
        f"\tchmod 700 {persist} 2>/dev/null || true\n"
        f"\tcp -a {state_dir / 'lockdown'}/*.plist /var/lib/lockdown/ 2>/dev/null || true\n"
        "}\n"
        "\n"
        f"command={shlex.quote(command.split()[0])}\n"
        f"command_args={shlex.quote(' '.join(command.split()[1:]))}\n"
    )


def _openrc_tunneld_unit(binary: str) -> str:
    command = _tunneld_command(binary)
    parts = command.split()
    return (
        "#!/sbin/openrc-run\n"
        "name=\"ios-wifi-loc-tunneld\"\n"
        "command_background=yes\n"
        'pidfile="/run/ios-wifi-loc-tunneld.pid"\n'
        "\n"
        "depend() {\n"
        "\tneed net\n"
        "}\n"
        "\n"
        f"command={shlex.quote(parts[0])}\n"
        f"command_args={shlex.quote(' '.join(parts[1:]))}\n"
    )


def install_files(
    root: Path,
    *,
    state_dir: Path,
    executable: str | None = None,
    interface: str | None = None,
    binary: str | None = None,
    require_auth: bool = False,
    port: int | None = None,
) -> dict:
    root = root.resolve()
    kind = detect_init(root)
    notes: list[str] = []
    if kind == "procd":
        notes.extend(migrate_openwrt_state(root, state_dir))
    state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(state_dir, 0o700)
    (state_dir / "lockdown").mkdir(parents=True, mode=0o700, exist_ok=True)
    load_or_create_secret(secret_path(state_dir))
    exe = executable or os.environ.get("IOS_WIFI_LOC_PYTHON", "") or "python3"
    resolved_binary = binary or infer_binary_from_python(exe) or "pymobiledevice3"
    installed = None
    tunneld_unit = None
    if kind == "openrc":
        destination = root / "etc/init.d/ios-wifi-loc"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            _openrc_unit(exe, state_dir, interface, resolved_binary, require_auth=require_auth, port=port),
            encoding="utf-8",
        )
        os.chmod(destination, 0o755)
        companion = root / "etc/init.d/ios-wifi-loc-tunneld"
        companion.write_text(_openrc_tunneld_unit(resolved_binary), encoding="utf-8")
        os.chmod(companion, 0o755)
        installed = destination
        tunneld_unit = companion
    elif kind == "systemd":
        destination = root / "etc/systemd/system/ios-wifi-loc.service"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            _systemd_unit(exe, state_dir, interface, resolved_binary, require_auth=require_auth, port=port),
            encoding="utf-8",
        )
        companion = root / "etc/systemd/system/ios-wifi-loc-tunneld.service"
        companion.write_text(_systemd_tunneld_unit(resolved_binary), encoding="utf-8")
        installed = destination
        tunneld_unit = companion
    elif kind == "procd":
        destination = root / "etc/init.d/ios-wifi-loc"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            _procd_unit(exe, state_dir, interface, resolved_binary, require_auth=require_auth, port=port),
            encoding="utf-8",
        )
        os.chmod(destination, 0o755)
        installed = destination
    return {
        "init": kind,
        "unit": None if installed is None else str(installed),
        "tunneld_unit": None if tunneld_unit is None else str(tunneld_unit),
        "secret_path": str(secret_path(state_dir)),
        "state_dir": str(state_dir),
        "binary": resolved_binary,
        "require_auth": require_auth,
        "port": _normalize_port(port),
        "migration": notes,
    }


def uninstall_files(root: Path, *, state_dir: Path, purge_state: bool) -> dict:
    removed = []
    for relative in (
        "etc/systemd/system/ios-wifi-loc.service",
        "etc/systemd/system/ios-wifi-loc-tunneld.service",
        "etc/init.d/ios-wifi-loc",
        "etc/init.d/ios-wifi-loc-tunneld",
    ):
        path = root / relative
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if purge_state and state_dir.exists():
        for child in list(state_dir.rglob("*"))[::-1]:
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        state_dir.rmdir()
        removed.append(str(state_dir))
    return {"removed": removed}
