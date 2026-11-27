from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fakes" / "pymobiledevice3"
DURATION_S = 60


def test_console_stays_up_for_one_measured_minute(tmp_path):
    """60 seconds of HTTP against the fake upstream. This is not phone stability."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["IOS_WIFI_LOC_FAKE_LOG"] = str(tmp_path / "argv.log")
    env["IOS_WIFI_LOC_FAKE_DEVICES"] = "[]"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ios_wifi_loc",
            "--state-dir",
            str(tmp_path / "state"),
            "--binary",
            str(FAKE),
            "serve",
            "--no-watch",
            "--port",
            "0",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    from ios_wifi_loc.metrics import sample_process

    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line.startswith("LISTENING "), line
    host, port = line.split()[1], line.split()[2]
    samples = []
    ok = 0
    started = time.monotonic()
    try:
        while time.monotonic() - started < DURATION_S:
            samples.append(sample_process(proc.pid))
            with urllib.request.urlopen(f"http://{host}:{port}/", timeout=5) as response:
                if response.status == 200 and "手机定位" in response.read().decode():
                    ok += 1
            time.sleep(2)
        samples.append(sample_process(proc.pid))
        elapsed = time.monotonic() - started
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    cpu = samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"]
    rss = [item["rss_kib"] for item in samples]
    report = {
        "duration_requested_s": DURATION_S,
        "actual_elapsed_s": round(elapsed, 3),
        "samples": len(samples),
        "requests_ok": ok,
        "rss_kib_start": rss[0],
        "rss_kib_end": rss[-1],
        "rss_kib_max": max(rss),
        "cpu_seconds": round(cpu, 3),
        "cpu_fraction": round(cpu / elapsed, 4),
        "method": "read /proc/<pid>/status VmRSS and /proc/<pid>/stat utime+stime every 2s",
        "upstream": "fake pymobiledevice3 process",
        "phone_location_tested": False,
    }
    text = json.dumps(report, indent=2)
    (tmp_path / "stability.json").write_text(text, encoding="utf-8")
    Path("/tmp/ios-wifi-loc-stability.json").write_text(text, encoding="utf-8")
    assert report["actual_elapsed_s"] >= DURATION_S
    assert ok >= 20
    assert report["cpu_fraction"] < 0.5
    assert report["rss_kib_max"] - report["rss_kib_start"] < 32768
    assert report["phone_location_tested"] is False
