from __future__ import annotations

import os
import platform
import re
import shlex
from pathlib import Path

from ios_wifi_loc.service import load_or_create_secret, secret_path

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
    systemd = root / "usr/lib/systemd/system"
    if systemd.is_dir() or (root / "etc/systemd/system").is_dir():
        return "systemd"
    return "none"


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
        warnings.append("检测到 OpenWrt。启动脚本只放 procd，不改防火墙、路由或 PassWall。软件包由 oneclick-install.sh 处理。")
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


def _serve_command(executable: str, state_dir: Path, interface: str | None) -> str:
    parts = [executable, "-m", "ios_wifi_loc", "serve", "--state-dir", str(state_dir)]
    checked = validate_interface(interface)
    if checked:
        parts.extend(["--interface", checked])
    return " ".join(shlex.quote(part) for part in parts)


def _unit(executable: str, state_dir: Path, kind: str, interface: str | None = None) -> str:
    command = _serve_command(executable, state_dir, interface)
    if kind == "systemd":
        return (
            "[Unit]\n"
            "Description=iPhone Wi-Fi location console\n"
            "After=network.target\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={command}\n"
            "Restart=on-failure\n"
            "RestartSec=5\n"
            "StartLimitIntervalSec=300\n"
            "StartLimitBurst=5\n"
            "NoNewPrivileges=true\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
    return (
        "#!/bin/sh /etc/rc.common\n"
        "START=99\n"
        "USE_PROCD=1\n"
        "start_service() {\n"
        "\tprocd_open_instance\n"
        f"\tprocd_set_param command {command}\n"
        "\tprocd_set_param respawn 3600 5 5\n"
        "\tprocd_close_instance\n"
        "}\n"
    )


def install_files(
    root: Path,
    *,
    state_dir: Path,
    executable: str | None = None,
    interface: str | None = None,
) -> dict:
    root = root.resolve()
    state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(state_dir, 0o700)
    load_or_create_secret(secret_path(state_dir))
    kind = detect_init(root)
    exe = executable or os.environ.get("IOS_WIFI_LOC_PYTHON", "") or "python3"
    installed = None
    if kind == "systemd":
        destination = root / "etc/systemd/system/ios-wifi-loc.service"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_unit(exe, state_dir, "systemd", interface), encoding="utf-8")
        installed = destination
    elif kind == "procd":
        destination = root / "etc/init.d/ios-wifi-loc"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(_unit(exe, state_dir, "procd", interface), encoding="utf-8")
        os.chmod(destination, 0o755)
        installed = destination
    return {"init": kind, "unit": None if installed is None else str(installed), "secret_path": str(secret_path(state_dir))}


def uninstall_files(root: Path, *, state_dir: Path, purge_state: bool) -> dict:
    removed = []
    for relative in ("etc/systemd/system/ios-wifi-loc.service", "etc/init.d/ios-wifi-loc"):
        path = root / relative
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if purge_state and state_dir.exists():
        for child in state_dir.iterdir():
            if child.is_file():
                child.unlink()
        state_dir.rmdir()
        removed.append(str(state_dir))
    return {"removed": removed}
