import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "oneclick-install.sh"
UNINSTALL = ROOT / "scripts" / "oneclick-uninstall.sh"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _fake_pm(log: Path) -> str:
    return f"""#!/bin/sh
printf '%s\\n' "$*" >> "{log}"
exit 0
"""


def _pip(log: Path, fail_requirements_once: bool) -> str:
    mark = log.parent / "pip-failed-once"
    fail = "1" if fail_requirements_once else "0"
    return f"""#!/bin/sh
printf '%s\\n' "$*" >> "{log}"
if [ "{fail}" = 1 ] && printf '%s' "$*" | grep -q requirements-upstream && [ ! -f "{mark}" ]; then
  : > "{mark}"
  exit 1
fi
exit 0
"""


def _run(args, env, check=True):
    result = subprocess.run(
        ["sh", str(args[0]), *args[1:]],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"{result.returncode}\\n{result.stdout}\\n{result.stderr}")
    return result


def _env(tmp_path: Path, **extra):
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}:{env['PATH']}"
    env["IOS_WIFI_LOC_SRC_PYTHONPATH"] = str(ROOT / "src")
    env["IOS_WIFI_LOC_PIP"] = str(tmp_path / "bin" / "pip-fake")
    env.update(extra)
    return env


def _openwrt(tmp_path: Path, manager: str) -> Path:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "openwrt_release").write_text("DISTRIB_ID='OpenWrt'\n", encoding="utf-8")
    log = tmp_path / f"{manager}.log"
    _write(tmp_path / "bin" / manager, _fake_pm(log))
    _write(tmp_path / "bin" / "pip-fake", _pip(tmp_path / "pip.log", False))
    return root


def test_dry_run_openwrt_opkg_does_not_call_opkg(tmp_path):
    root = _openwrt(tmp_path, "opkg")
    result = _run([INSTALL, "--dry-run", "--root", str(root), "--interface", "br-lan"], _env(tmp_path))
    assert "opkg" in result.stdout
    assert "python3 python3-pip usbmuxd" in result.stdout
    assert "MemTotal=" in result.stdout
    assert "可用磁盘" in result.stdout
    assert "不会修改路由、防火墙或 PassWall" in result.stdout
    assert "这是预览" in result.stdout
    assert not (tmp_path / "opkg.log").exists()
    assert not (root / "etc" / "init.d" / "ios-wifi-loc").exists()


def test_dry_run_openwrt_apk_when_opkg_is_absent(tmp_path):
    root = _openwrt(tmp_path, "apk")
    result = _run([INSTALL, "--dry-run", "--root", str(root)], _env(tmp_path))
    assert "包管理器：apk" in result.stdout
    assert not (tmp_path / "apk.log").exists()


def test_dry_run_debian_apt_get(tmp_path):
    root = tmp_path / "debian"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "debian_version").write_text("12\n", encoding="utf-8")
    log = tmp_path / "apt.log"
    _write(tmp_path / "bin" / "apt-get", _fake_pm(log))
    _write(tmp_path / "bin" / "pip-fake", _pip(tmp_path / "pip.log", False))
    result = _run([INSTALL, "--dry-run", "--root", str(root), "--interface", "br-lan"], _env(tmp_path))
    assert "apt-get" in result.stdout
    assert "python3-venv" in result.stdout
    assert not log.exists()


def test_rejects_wildcard_bind(tmp_path):
    root = _openwrt(tmp_path, "opkg")
    result = _run(
        [INSTALL, "--dry-run", "--root", str(root), "--interface", "0.0.0.0"],
        _env(tmp_path),
        check=False,
    )
    assert result.returncode == 2
    assert "0.0.0.0" in result.stderr


def test_openwrt_install_writes_interface_and_secret(tmp_path):
    root = _openwrt(tmp_path, "opkg")
    prefix = tmp_path / "prefix"
    state = tmp_path / "state"
    result = _run(
        [
            INSTALL,
            "--root",
            str(root),
            "--prefix",
            str(prefix),
            "--state-dir",
            str(state),
            "--interface",
            "br-lan",
        ],
        _env(tmp_path),
    )
    opkg = (tmp_path / "opkg.log").read_text(encoding="utf-8")
    assert "install python3 python3-pip usbmuxd" in opkg
    assert "python3-dev" not in opkg
    assert "firewall" not in opkg
    unit = (root / "etc" / "init.d" / "ios-wifi-loc").read_text(encoding="utf-8")
    assert "USE_PROCD=1" in unit
    assert "--interface br-lan" in unit
    assert "0.0.0.0" not in unit
    assert "firewall" not in unit
    secret = state / "web.secret"
    assert secret.exists()
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert secret.read_text(encoding="utf-8").strip() not in result.stdout
    assert str(secret) in result.stdout
    pip = (tmp_path / "pip.log").read_text(encoding="utf-8")
    assert "requirements-upstream.txt" in pip
    assert (prefix / "venv" / "bin" / "python3").exists()


def test_pip_failure_installs_build_packages_once(tmp_path):
    root = _openwrt(tmp_path, "opkg")
    _write(tmp_path / "bin" / "pip-fake", _pip(tmp_path / "pip.log", True))
    _run(
        [INSTALL, "--root", str(root), "--prefix", str(tmp_path / "prefix"), "--state-dir", str(tmp_path / "state")],
        _env(tmp_path),
    )
    opkg = (tmp_path / "opkg.log").read_text(encoding="utf-8")
    assert "install gcc" in opkg
    assert "install libimobiledevice" in opkg
    pip_lines = (tmp_path / "pip.log").read_text(encoding="utf-8").splitlines()
    requirement_calls = [line for line in pip_lines if "requirements-upstream.txt" in line]
    assert len(requirement_calls) == 2


def test_missing_venv_uses_private_prefix(tmp_path):
    root = _openwrt(tmp_path, "opkg")
    real = shutil.which("python3")
    assert real
    fake = tmp_path / "bin" / "python3"
    _write(
        fake,
        f"""#!/bin/sh
if [ "$1" = "-c" ] && printf '%s' "$2" | grep -q 'import venv'; then
  exit 1
fi
exec "{real}" "$@"
""",
    )
    prefix = tmp_path / "prefix"
    result = _run(
        [INSTALL, "--root", str(root), "--prefix", str(prefix), "--state-dir", str(tmp_path / "state")],
        _env(tmp_path),
    )
    assert "没有 venv 模块" in result.stdout
    assert "不写入系统 site-packages" in result.stdout
    wrapper = prefix / "bin" / "ios-wifi-loc-python"
    assert wrapper.exists()
    assert not (prefix / "venv").exists()
    pip = (tmp_path / "pip.log").read_text(encoding="utf-8")
    assert f"--target {prefix / 'pydeps'}" in pip
    opkg = (tmp_path / "opkg.log").read_text(encoding="utf-8")
    assert "python3-venv" in opkg


def test_uninstall_removes_prefix_and_can_preview(tmp_path):
    root = _openwrt(tmp_path, "opkg")
    prefix = tmp_path / "prefix"
    state = tmp_path / "state"
    env = _env(tmp_path)
    _run([INSTALL, "--root", str(root), "--prefix", str(prefix), "--state-dir", str(state)], env)
    preview = _run(
        [UNINSTALL, "--dry-run", "--root", str(root), "--prefix", str(prefix), "--state-dir", str(state)],
        env,
    )
    assert "这是预览" in preview.stdout
    assert prefix.exists()
    assert (root / "etc" / "init.d" / "ios-wifi-loc").exists()
    _run([UNINSTALL, "--root", str(root), "--prefix", str(prefix), "--state-dir", str(state)], env)
    assert not prefix.exists()
    assert not (root / "etc" / "init.d" / "ios-wifi-loc").exists()
    assert (state / "web.secret").exists()


def test_host_dry_run_does_not_require_claiming_a_device():
    result = subprocess.run(
        ["sh", str(INSTALL), "--dry-run"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "这是预览" in result.stdout
    assert "apt-get" in result.stdout or "opkg" in result.stdout or "apk" in result.stdout


def test_service_interface_rejects_wildcard_bind(tmp_path):
    from ios_wifi_loc.install import install_files

    root = tmp_path / "systemd"
    (root / "usr/lib/systemd/system").mkdir(parents=True)
    try:
        install_files(root, state_dir=tmp_path / "state", interface="0.0.0.0")
    except ValueError as exc:
        assert "0.0.0.0" in str(exc)
    else:
        raise AssertionError("wildcard bind was accepted")
