"""Keep a simulated location sticky on iOS 17+ by refreshing the same DVT session.

pymobiledevice3 11.63.1 ``developer dvt simulate-location set`` only calls
``LocationSimulation.set(lat, lon)`` once, then ``await OSUTILS.wait_return()``.
On POSIX that wait is an async signal handler (stdin=DEVNULL does not EOF-exit
the process). The child stays alive, but iOS 17+/26/27 CoreLocation can still
interleave live GNSS / Wi-Fi fixes with a one-shot developer override, which
shows up on the phone as a regular real/virtual flicker (often about 1 Hz).

Mature tools (for example ios-location-server) therefore call ``set()`` again
on the *same* open ``LocationSimulation`` channel every few seconds. This
module does that via the pymobiledevice3 Python API when it is available,
and leaves the CLI child path in place for the fake binary used in tests.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from ios_wifi_loc.tunneld import tunneld_url
from ios_wifi_loc.upstream import Target


def heartbeat_interval() -> float:
    raw = os.environ.get("IOS_WIFI_LOC_SIM_HEARTBEAT", "1")
    try:
        return max(0.3, min(10.0, float(raw)))
    except ValueError:
        return 1.0


def prefer_api_heartbeat(binary: str, profile: str, use_tunnel: bool) -> bool:
    """Use the in-process DVT heartbeat when a real pymobiledevice3 API is available."""
    if not use_tunnel or profile != "ios17":
        return False
    if os.environ.get("IOS_WIFI_LOC_FORCE_CLI"):
        return False
    if os.environ.get("IOS_WIFI_LOC_FAKE_LOG") or os.environ.get("IOS_WIFI_LOC_FAKE_DEVICES"):
        return False
    path = Path(binary)
    text = str(path)
    if "tests/fakes" in text.replace("\\", "/") or path.name == "pymobiledevice3" and "fakes" in text:
        return False
    try:
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider  # noqa: F401
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation  # noqa: F401
        from pymobiledevice3.tunneld.api import get_tunneld_device_by_udid  # noqa: F401
    except ImportError:
        return False
    return True


def tunneld_address() -> tuple[str, int]:
    parsed = urlparse(tunneld_url())
    return (parsed.hostname or "127.0.0.1", parsed.port or 49151)


def simulate_command_argv(
    python: str,
    store_dir: Path | str,
    target: Target,
    latitude: str,
    longitude: str,
    *,
    interval: float | None = None,
) -> list[str]:
    parts = [
        python,
        "-m",
        "ios_wifi_loc",
        "--state-dir",
        str(store_dir),
        "_simulate",
        "--udid",
        target.udid,
        "--latitude",
        str(latitude),
        "--longitude",
        str(longitude),
        "--interval",
        str(heartbeat_interval() if interval is None else interval),
    ]
    if target.host:
        parts.extend(["--host", target.host])
    return parts


async def refresh_location(sim, latitude: float, longitude: float, interval: float, stopped: Callable[[], bool], *, sleep=asyncio.sleep) -> int:
    """Call set() immediately, then again every ``interval`` seconds until stopped.

    Never calls ``clear()``: stopping the loop just leaves the DVT context, and
    a user-requested restore goes through the dedicated clear command.
    """
    await sim.set(latitude, longitude)
    count = 1
    while not stopped():
        await sleep(interval)
        if stopped():
            break
        await sim.set(latitude, longitude)
        count += 1
    return count


async def _open_rsd(udid: str):
    from pymobiledevice3.tunneld.api import get_tunneld_device_by_udid

    # pymobiledevice3==11.63.1 signatures (PyPI wheel):
    #   async def get_tunneld_device_by_udid(udid, tunneld_address: tuple[str, int] = ("127.0.0.1", 49151))
    #   DvtProvider / LocationSimulation are async context managers (__aenter__/__aexit__)
    #   async def LocationSimulation.set(self, latitude, longitude)
    # Await the coroutine when present; keep a sync fallback for older/newer wheels.
    result = get_tunneld_device_by_udid(udid, tunneld_address())
    if asyncio.iscoroutine(result):
        result = await result
    return result


async def hold_location_via_api(udid: str, latitude: float, longitude: float, interval: float, stopped: Callable[[], bool]) -> int:
    from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
    from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

    rsd = await _open_rsd(udid)
    if rsd is None:
        print(f"tunneld has no tunnel for {udid}", file=sys.stderr)
        return 4
    try:
        async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as sim:
            print(f"dvt location heartbeat {latitude} {longitude} every {interval}s", flush=True)
            await refresh_location(sim, latitude, longitude, interval, stopped)
        return 0
    finally:
        close = getattr(rsd, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


def run_simulate(args: object) -> int:
    try:
        udid = str(getattr(args, "udid"))
        latitude = float(getattr(args, "latitude"))
        longitude = float(getattr(args, "longitude"))
        interval = float(getattr(args, "interval") or heartbeat_interval())
    except (TypeError, ValueError):
        return 2
    interval = max(0.3, min(10.0, interval))
    stop = {"flag": False}

    def _handle(_signum: int, _frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    try:
        return asyncio.run(hold_location_via_api(udid, latitude, longitude, interval, lambda: stop["flag"]))
    except KeyboardInterrupt:
        return 0
    except ImportError as exc:
        print(f"pymobiledevice3 API unavailable: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"dvt location heartbeat failed: {exc}", file=sys.stderr)
        return 4
