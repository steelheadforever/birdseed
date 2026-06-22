"""Device health, read off the running system. Used by the server's /api/health.

Everything here is *best-effort*: each probe is wrapped so a missing command or
an unreadable file yields None instead of an exception. That's not just defensive
hygiene — it's what lets the exact same server run on the Mac (where vcgencmd,
iw, and /sys/class/thermal don't exist) for development, and on the Pi for real.
A health field that's None simply renders as "—" in the UI.

The server stays read-only with respect to clips and the camera; reading system
health is a different thing entirely (it touches no birdseed state, just asks
the OS how it's doing), so it lives comfortably on the serving side.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import state

_PI_DIR = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], timeout: float = 4.0) -> str | None:
    """Run a command, return stripped stdout, or None on any failure."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def wifi() -> dict:
    """Signal strength + link rate from `iw`. The number that decides whether
    the feeder can reach the AP from out in the yard."""
    link = _run(["iw", "dev", "wlan0", "link"])
    if not link or "Not connected" in link:
        return {"connected": False, "ssid": None, "signal_dbm": None, "bitrate_mbps": None}
    ssid = re.search(r"SSID:\s*(.+)", link)
    signal = re.search(r"signal:\s*(-?\d+)\s*dBm", link)
    bitrate = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", link)
    return {
        "connected": True,
        "ssid": ssid.group(1).strip() if ssid else None,
        "signal_dbm": int(signal.group(1)) if signal else None,
        "bitrate_mbps": float(bitrate.group(1)) if bitrate else None,
    }


# The bits in vcgencmd's throttled bitmask. Low bits = happening now, high bits
# (>=16) = has happened since boot. Undervoltage is the one that matters for a
# solar build, which is why we surface it in words, not hex.
_THROTTLE_BITS = {
    0: "undervoltage now",
    1: "arm frequency capped now",
    2: "throttled now",
    3: "soft temperature limit now",
    16: "undervoltage since boot",
    17: "arm frequency capped since boot",
    18: "throttled since boot",
    19: "soft temperature limit since boot",
}


def power() -> dict:
    """Decode `vcgencmd get_throttled` into plain language."""
    raw = _run(["vcgencmd", "get_throttled"])
    if not raw:
        return {"raw": None, "healthy": None, "flags": []}
    m = re.search(r"throttled=0x([0-9a-fA-F]+)", raw)
    if not m:
        return {"raw": raw, "healthy": None, "flags": []}
    bits = int(m.group(1), 16)
    flags = [label for bit, label in _THROTTLE_BITS.items() if bits & (1 << bit)]
    return {"raw": f"0x{bits:x}", "healthy": bits == 0, "flags": flags}


def temperature_c() -> float | None:
    """SoC temperature in Celsius. Throttling starts around 80–85 °C; an outdoor
    enclosure baking in the sun is the realistic way to get there."""
    raw = _run(["vcgencmd", "measure_temp"])
    if raw:
        m = re.search(r"temp=([\d.]+)", raw)
        if m:
            return float(m.group(1))
    # Fallback that works without vcgencmd (and on some non-Pi Linux).
    milli = _read("/sys/class/thermal/thermal_zone0/temp")
    return round(int(milli) / 1000, 1) if milli and milli.isdigit() else None


def storage(clips_dir: Path, cap_bytes: int | None) -> dict:
    """How full the ring buffer is, and how much card is left under it."""
    clips = sorted(clips_dir.glob("clip_*.mp4")) if clips_dir.is_dir() else []
    used = sum(p.stat().st_size for p in clips)
    info: dict = {
        "clip_count": len(clips),
        "clips_bytes": used,
        "cap_bytes": cap_bytes,
        "cap_used_pct": round(100 * used / cap_bytes, 1) if cap_bytes else None,
        "oldest": clips[0].name if clips else None,
        "newest": clips[-1].name if clips else None,
    }
    try:
        du = shutil.disk_usage(clips_dir if clips_dir.is_dir() else _PI_DIR)
        info["disk_free_bytes"] = du.free
        info["disk_total_bytes"] = du.total
    except OSError:
        info["disk_free_bytes"] = info["disk_total_bytes"] = None
    return info


def system() -> dict:
    """Uptime, load, memory, clock sync, and service health."""
    info: dict = {}

    up = _read("/proc/uptime")
    info["uptime_s"] = float(up.split()[0]) if up else None

    load = _read("/proc/loadavg")
    info["load_1m"] = float(load.split()[0]) if load else None

    mem = _read("/proc/meminfo")
    if mem:
        fields = dict(
            (k.rstrip(":"), int(v))
            for k, v, *_ in (line.split() for line in mem.splitlines())
        )
        total, avail = fields.get("MemTotal"), fields.get("MemAvailable")
        info["mem_total_kb"] = total
        info["mem_used_pct"] = round(100 * (total - avail) / total, 1) if total and avail else None

    # No RTC on a Pi: if it boots offline and records before NTP syncs, clips get
    # misnamed. The filename *is* our metadata, so surface whether time is sound.
    info["ntp_synced"] = _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]) == "yes"
    info["time"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    info["services"] = {
        svc: (_run(["systemctl", "is-active", svc]) or "unknown")
        for svc in ("birdseed-recorder", "birdseed-server")
    }
    return info


def build() -> dict:
    """A fingerprint of the deployed source, so you can tell at a glance whether
    a deploy actually landed — the failure that cost us an hour. git isn't on the
    Pi (code arrives by scp), so we hash the files instead of reading a SHA."""
    targets = sorted((_PI_DIR / "birdseed").glob("*.py")) + [_PI_DIR / "web" / "index.html"]
    h = hashlib.sha256()
    newest = 0.0
    for f in targets:
        try:
            h.update(f.read_bytes())
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            continue
    return {
        "fingerprint": h.hexdigest()[:12],
        "newest_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(newest)) if newest else None,
    }


def health(clips_dir: Path, cap_bytes: int | None) -> dict:
    """Everything the settings tab shows, in one read."""
    return {
        "wifi": wifi(),
        "power": power(),
        "temperature_c": temperature_c(),
        "storage": storage(clips_dir, cap_bytes),
        "system": system(),
        "build": build(),
        "camera": state.read_camera_state(),
    }
