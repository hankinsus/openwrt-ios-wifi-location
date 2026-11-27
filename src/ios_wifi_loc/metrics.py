from __future__ import annotations

import os
from pathlib import Path


def sample_process(pid: int) -> dict[str, float]:
    """Read VmRSS and CPU time from /proc. This does not measure a phone."""
    status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    rss = 0.0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            rss = float(line.split()[1])
            break
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    after = stat.rsplit(")", 1)[1].split()
    ticks = int(after[11]) + int(after[12])
    hz = os.sysconf("SC_CLK_TCK") or 100
    return {"rss_kib": rss, "cpu_seconds": ticks / hz}
