from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fakes" / "pymobiledevice3"
UDID = "0123456789abcdef0123456789abcdef01234567"
OTHER = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"


@pytest.fixture
def cli(tmp_path):
    state = tmp_path / "state"
    log = tmp_path / "argv.log"
    counter = tmp_path / "count"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["IOS_WIFI_LOC_FAKE_LOG"] = str(log)
    env["IOS_WIFI_LOC_FAKE_COUNTER"] = str(counter)
    env["IOS_WIFI_LOC_FAKE_DEVICES"] = json.dumps([UDID])
    env.pop("PYMOBILEDEVICE3_UDID", None)
    env.pop("PYMOBILEDEVICE3_RECONNECT_ANY", None)

    def run(args, extra_env=None, timeout=15, global_args=None):
        local = env.copy()
        if extra_env:
            local.update(extra_env)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "ios_wifi_loc",
                "--state-dir",
                str(state),
                "--binary",
                str(FAKE),
                "--json",
                *(global_args or []),
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=local,
            timeout=timeout,
        )
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return proc, payload

    def logged():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]

    yield type("Cli", (), {"run": staticmethod(run), "logged": staticmethod(logged), "state": state, "env": env, "log": log})
    path = state / "state.json"
    if path.exists():
        session = json.loads(path.read_text(encoding="utf-8")).get("session") or {}
        pid = session.get("pid")
        if isinstance(pid, int) and pid > 1:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_coords_and_identifiers():
    from ios_wifi_loc.coords import CoordError, parse_pair
    from ios_wifi_loc.identifiers import IdentifierError, validate_host, validate_udid

    assert parse_pair(" -90 ", "180") == ("-90", "180")
    assert parse_pair("90", "-180") == ("90", "-180")
    assert parse_pair("40.690008", "-74.045843") == ("40.690008", "-74.045843")
    for bad in ["91", "-90.0001", "nan", "inf", "1e2", "", "10;rm", "10,5", "  ", "--1"]:
        with pytest.raises(CoordError):
            parse_pair(bad, "0")
    with pytest.raises(CoordError):
        parse_pair("0", "180.0001")
    validate_udid(UDID)
    validate_udid("01234567-89ABCDEF01234567")
    validate_udid("12345678-1234-1234-1234-123456789abc")
    with pytest.raises(IdentifierError):
        validate_udid("abc;rm -rf /")
    validate_host("192.0.2.10")
    with pytest.raises(IdentifierError):
        validate_host("192.0.2.1;reboot")
    with pytest.raises(IdentifierError):
        validate_host("999.1.1.1")


def test_redact_removes_key_material():
    from ios_wifi_loc.redact import redact

    pem = "-----BEGIN " + "RSA PRIVATE KEY-----\n" + ("A" * 100) + "\n-----END " + "RSA PRIVATE KEY-----"
    raw = pem + "\nHostPrivateKey = " + ("B" * 90) + "\nWiFiMACAddress aa:bb"
    cleaned = redact(raw)
    assert "BEGIN RSA" not in cleaned
    assert "HostPrivateKey" not in cleaned
    assert "B" * 90 not in cleaned
    assert "已隐藏" in cleaned


def test_plan_flags_and_banned_commands():
    from ios_wifi_loc.upstream import PlanError, Target, location_argv, usbmux_list_argv

    target = Target(UDID, "mobdev2", host="192.0.2.10")
    argv = location_argv("pymobiledevice3", target, "set", "ios17", "-33.8", "151.2")
    assert argv[1:6] == ["developer", "dvt", "simulate-location", "set", "--udid"]
    assert "--mobdev2-host" in argv and "--mobdev2" not in argv
    assert argv[argv.index("--") + 1 :] == ["-33.8", "151.2"]
    plain = Target(UDID, "mobdev2")
    assert "--mobdev2" in location_argv("pymobiledevice3", plain, "clear", "ios17")
    assert "--usbmux" not in location_argv("pymobiledevice3", Target(UDID, "usbmux"), "clear", "pre17")
    assert usbmux_list_argv("pymobiledevice3", kind="network")[-2:] == ["--network", "--simple"]
    with pytest.raises(PlanError):
        location_argv("pymobiledevice3;rm", Target(UDID, "usbmux"), "set", "ios17", "1", "2")


def test_version_classes_and_openwrt_grade():
    from ios_wifi_loc.doctor import grade_host
    from ios_wifi_loc.upstream import classify_product_version

    assert classify_product_version("16.7.1") == "pre17"
    assert classify_product_version("17.0") == "ios17_needs_tunneld"
    assert classify_product_version("17.3.1") == "ios17_needs_tunneld"
    assert classify_product_version("17.4") == "ios17"
    assert classify_product_version("18.2") == "ios17"
    absent = grade_host(openwrt_text=None, machine="x86_64", mem_kb=8_000_000, upstream_help_ok=True)
    assert absent["openwrt"]["level"] == "not_observed"
    assert absent["xe300_128mb_mips"]["verdict"] == "not_promised"
    small = grade_host(openwrt_text='DISTRIB_ARCH="mips"', machine="mips", mem_kb=128 * 1024, upstream_help_ok=False)
    assert small["low_memory"]
    assert "不承诺" in small["low_memory"]
    assert small["aarch64_same_as_r4s_cpu_class"] is False


def test_runner_timeout_and_env_strip(tmp_path):
    from ios_wifi_loc.runner import child_env, run

    env = child_env({"PATH": "/usr/bin", "PYMOBILEDEVICE3_RECONNECT_ANY": "1", "USBMUXD_SOCKET_ADDRESS": "/tmp/x"})
    assert "PYMOBILEDEVICE3_RECONNECT_ANY" not in env
    assert "USBMUXD_SOCKET_ADDRESS" not in env
    log = tmp_path / "argv.log"
    proc_env = child_env({"IOS_WIFI_LOC_FAKE_MODE": "timeout", "IOS_WIFI_LOC_FAKE_LOG": str(log)})
    result = run([str(FAKE), "usbmux", "list", "--network", "--simple"], timeout=0.4, env=proc_env)
    assert result.timed_out is True
    assert result.ok is False
    assert result.error == "timeout"


def test_requires_explicit_select_and_rejects_injection(cli):
    proc, payload = cli.run(["set", "--profile", "ios17", "--latitude", "10", "--longitude", "20", "--startup-grace", "0.2"])
    assert proc.returncode == 3
    assert payload["code"] == "NOT_SELECTED"
    proc, payload = cli.run(["set", "--profile", "ios17", "--latitude", "10;rm", "--longitude", "20"])
    assert proc.returncode == 2
    assert payload["code"] == "VALIDATION"
    assert all("simulate-location" not in item for item in cli.logged())
    proc, payload = cli.run(["select", "--udid", "abc;rm", "--transport", "usbmux"])
    assert proc.returncode == 2
    assert all("simulate-location" not in item for item in cli.logged())


def test_selects_requested_device_and_keeps_negative_coordinate(cli):
    cli.env["IOS_WIFI_LOC_FAKE_DEVICES"] = json.dumps([UDID, OTHER])
    listed, listing = cli.run(["devices"])
    assert listed.returncode == 0
    wifi = [item["udid"] for item in listing["details"]["devices"] if item["connection"] == "wifi"]
    assert wifi == [UDID, OTHER]
    chosen, payload = cli.run(["select", "--udid", OTHER, "--transport", "remotepairing"])
    assert chosen.returncode == 0
    proc, payload = cli.run(
        ["set", "--profile", "ios17", "--latitude", "40.6", "--longitude", "-74.0060", "--startup-grace", "0.3"]
    )
    assert proc.returncode == 0
    assert payload["code"] == "SET_HOLDING"
    calls = [item for item in cli.logged() if "simulate-location" in item and "set" in item]
    assert calls
    argv = calls[-1]
    assert OTHER in argv and UDID not in argv
    assert argv[argv.index("--") + 1 :] == ["40.6", "-74.006"]
    assert "--remotepairing" in argv


def test_pre17_short_set_and_legacy_refusal(cli):
    cli.run(["select", "--udid", UDID, "--transport", "usbmux"])
    proc, payload = cli.run(
        ["set", "--profile", "pre17", "--latitude", "1", "--longitude", "2"],
        extra_env={"IOS_WIFI_LOC_FAKE_MODE": "set-short-ok"},
    )
    assert payload["code"] == "SET_RETURNED"
    assert proc.returncode == 0
    cli.log.write_text("", encoding="utf-8")
    refused, payload = cli.run(
        ["set", "--profile", "auto", "--latitude", "1", "--longitude", "2", "--startup-grace", "0.2"],
        extra_env={"IOS_WIFI_LOC_FAKE_INFO": '{"ProductVersion": "17.3.1"}', "IOS_WIFI_LOC_FAKE_MODE": "ok"},
    )
    assert refused.returncode == 4
    assert payload["code"] == "LEGACY_TUNNEL_REQUIRED"
    assert all("simulate-location" not in item for item in cli.logged())


def test_upstream_failure_timeout_and_non_json(cli):
    cli.run(["select", "--udid", UDID, "--transport", "usbmux"])
    failed, payload = cli.run(
        ["set", "--profile", "pre17", "--latitude", "1", "--longitude", "2"],
        extra_env={"IOS_WIFI_LOC_FAKE_MODE": "set-fail"},
    )
    assert failed.returncode == 4
    assert payload["code"] == "UPSTREAM_FAILED"
    assert "不能确认" in payload["summary"] or "未被确认" in payload["summary"]
    slow, payload = cli.run(
        ["devices"],
        extra_env={"IOS_WIFI_LOC_FAKE_MODE": "timeout"},
        global_args=["--timeout", "0.4"],
        timeout=12,
    )
    assert slow.returncode == 0
    assert any(probe["timed_out"] for probe in payload["details"]["probes"])
    parsed, payload = cli.run(["devices"], extra_env={"IOS_WIFI_LOC_FAKE_MODE": "not-json"})
    assert parsed.returncode == 0
    assert payload["details"]["devices"] == []
    assert any(probe["parse_error"] for probe in payload["details"]["probes"])


def test_clear_does_not_claim_success_when_upstream_fails(cli):
    cli.run(["select", "--udid", UDID, "--transport", "usbmux"])
    cli.run(["set", "--profile", "ios17", "--latitude", "3", "--longitude", "4", "--startup-grace", "0.2"])
    proc, payload = cli.run(["clear", "--profile", "ios17"], extra_env={"IOS_WIFI_LOC_FAKE_CLEAR_CODE": "1"})
    assert proc.returncode == 6
    assert "不能确认已经恢复真实定位" in payload["summary"]
    assert "清除命令已成功返回" not in payload["summary"]
    ok, payload = cli.run(["clear", "--profile", "ios17"], extra_env={"IOS_WIFI_LOC_FAKE_CLEAR_CODE": "0"})
    assert ok.returncode == 0
    assert payload["code"] == "CLEARED"
    assert "清除命令已成功返回" in payload["summary"]


def test_reconnect_then_resume_requires_coordinates(cli):
    cli.run(["select", "--udid", UDID, "--transport", "mobdev2", "--host", "192.0.2.10"])
    missing, payload = cli.run(
        ["reconnect", "--attempts", "2", "--pause", "0"],
        extra_env={"IOS_WIFI_LOC_FAKE_EMPTY_LISTS": "1"},
    )
    assert missing.returncode == 0
    assert payload["code"] == "RECONNECTED"
    assert payload["details"]["attempts"][0]["matched"] is False
    assert payload["details"]["attempts"][1]["matched"] is True
    assert "没有修改定位" in payload["summary"]
    again, payload = cli.run(["reconnect", "--attempts", "1", "--pause", "0", "--resume"])
    assert again.returncode == 2
    assert payload["code"] == "VALIDATION"
    assert all("simulate-location" not in item or "set" not in item for item in cli.logged())


def test_reconnect_exhausted(cli):
    cli.run(["select", "--udid", UDID, "--transport", "usbmux"])
    proc, payload = cli.run(
        ["reconnect", "--attempts", "2", "--pause", "0"],
        extra_env={"IOS_WIFI_LOC_FAKE_EMPTY_LISTS": "9", "IOS_WIFI_LOC_FAKE_DEVICES": "[]"},
    )
    assert proc.returncode == 3
    assert payload["code"] == "NOT_FOUND"
    assert "定位没有被修改" in payload["summary"]


def test_smoke_is_dry_until_explicit(cli):
    cli.run(["select", "--udid", UDID, "--transport", "usbmux"])
    dry, payload = cli.run(["smoke", "--profile", "ios17", "--latitude", "31.2", "--longitude", "121.4"])
    assert dry.returncode == 0
    assert payload["code"] == "DRY_RUN"
    assert "未修改定位" in payload["summary"]
    assert all("simulate-location" not in item for item in cli.logged())
    blocked, payload = cli.run(
        ["smoke", "--profile", "ios17", "--latitude", "31.2", "--longitude", "121.4", "--execute"]
    )
    assert blocked.returncode == 2
    assert payload["code"] == "ACK_REQUIRED"
    live, payload = cli.run(
        [
            "smoke",
            "--execute",
            "--i-understand-this-sets-a-real-device",
            "--profile",
            "ios17",
            "--latitude",
            "31.2",
            "--longitude",
            "121.4",
            "--startup-grace",
            "0.2",
        ]
    )
    assert live.returncode == 0
    assert payload["code"] == "SET_HOLDING"
    assert any("simulate-location" in item and "set" in item for item in cli.logged())


def test_usb_record_is_not_a_wifi_target(cli):
    data = {"version": 1, "selected": None, "session": None, "discovery": [{"udid": UDID, "connection": "usb", "source": "usbmux_usb"}]}
    cli.state.mkdir(parents=True)
    (cli.state / "state.json").write_text(json.dumps(data), encoding="utf-8")
    proc, payload = cli.run(["select", "--udid", UDID])
    assert proc.returncode == 2
    assert payload["code"] == "USB_REFUSED"


def test_doctor_does_not_promise_openwrt_or_a_phone(cli):
    proc, payload = cli.run(["doctor"])
    assert proc.returncode == 0
    grade = payload["details"]["grade"]
    assert grade["openwrt"]["level"] == "not_observed"
    assert grade["xe300_128mb_mips"]["verdict"] == "not_promised"
    assert grade["physical_iphone"]["verdict"] == "not_attached"
    assert payload["details"]["machine"]
    dvt = [row for row in payload["details"]["help"] if row["argv"][:3] == ["developer", "dvt", "simulate-location"]]
    assert dvt and dvt[0]["returncode"] == 0


def test_pair_guide_does_not_call_upstream(cli):
    proc, payload = cli.run(["pair-guide"])
    assert proc.returncode == 0
    assert "不执行配对" in payload["summary"]
    assert cli.logged() == []


def test_foreground_signal_does_not_claim_cleanup(cli):
    cli.run(["select", "--udid", UDID, "--transport", "usbmux"])
    env = cli.env.copy()
    env["IOS_WIFI_LOC_FAKE_CLEAR_CODE"] = "1"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ios_wifi_loc",
            "--state-dir",
            str(cli.state),
            "--binary",
            str(FAKE),
            "set",
            "--foreground",
            "--profile",
            "ios17",
            "--latitude",
            "10",
            "--longitude",
            "20",
            "--startup-grace",
            "0.2",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = ""
        deadline = time.monotonic() + 8
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line.startswith("READY "):
                ready = line
                break
        assert ready.startswith("READY "), proc.stderr.read() if proc.stderr else ready
        os.kill(proc.pid, signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)
    text = ready + (stdout or "") + (stderr or "")
    assert proc.returncode == 6
    assert "不能确认已经恢复真实定位" in text
    assert "清除命令已成功返回" not in text


def test_interface_listing_uses_names_not_link_addresses():
    from ios_wifi_loc.doctor import _interfaces
    from ios_wifi_loc.identifiers import validate_host

    if not Path("/sys/class/net").exists():
        return
    for row in _interfaces():
        assert row["name"] and row["name"] != "lo"
        assert "address" not in row
        for addr in row["inet"]:
            validate_host(addr)


def test_repository_does_not_claim_hardware_success():
    banned = ["真机测试成功", "已在真机验证通过", "无需 USB", "XE300 可以运行", "Simulator 已验证"]
    roots = [ROOT / "src", ROOT / "docs", ROOT / "README.md"]
    text = []
    for root in roots:
        if root.is_file():
            text.append(root.read_text(encoding="utf-8"))
        elif root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    text.append(path.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(text)
    for phrase in banned:
        assert phrase not in blob


@pytest.mark.upstream
def test_installed_upstream_help():
    if not shutil_which("pymobiledevice3"):
        pytest.skip("pymobiledevice3 is not installed on PATH")
    script = ROOT / "scripts" / "verify_upstream_help.py"
    subprocess.check_call([sys.executable, str(script), "--out", str(ROOT / "reports" / "upstream-help-pytest")])


def shutil_which(name: str):
    from shutil import which

    return which(name)
