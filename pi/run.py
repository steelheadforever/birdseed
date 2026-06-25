#!/usr/bin/env python3
"""Entry point. Picks a backend and runs the capture loop.

Defaults to the mock backend everywhere except a real Pi, so you can run it on
your Mac right now. Force a backend with BIRDSEED_BACKEND=mock|hardware.

    python3 pi/run.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the birdseed package importable no matter where this is run from.
sys.path.insert(0, str(Path(__file__).parent))

from birdseed.recorder import Recorder


def _on_a_pi() -> bool:
    """Cheap heuristic: real Pis advertise their model here."""
    model = Path("/proc/device-tree/model")
    return model.exists() and "raspberry pi" in model.read_text(errors="ignore").lower()


def make_backends():
    backend = os.environ.get("BIRDSEED_BACKEND") or ("hardware" if _on_a_pi() else "mock")
    if backend == "hardware":
        from birdseed.hardware import GpioPirSensor, Picamera2Camera  # Pi-only imports
        print("backend: hardware (picamera2 + GPIO)")
        return GpioPirSensor(), Picamera2Camera()
    print("backend: mock (no hardware)")
    from birdseed.mock import MockCamera, MockMotionSensor
    return MockMotionSensor(), MockCamera()


def main() -> None:
    sensor, camera = make_backends()
    # Same override the server reads (BIRDSEED_CLIPS_DIR), so the two processes
    # always agree on where clips live — they default to pi/clips, but if one is
    # pointed elsewhere the other follows. (They MUST agree: the recorder deletes
    # from here what the server lists from there.)
    clips_dir = Path(os.environ.get("BIRDSEED_CLIPS_DIR", Path(__file__).parent / "clips"))
    # Policy lives here, not in the Recorder: how big the on-disk ring buffer is
    # allowed to grow. Sized for this build's 32 GB card — ~16 GB of clips leaves
    # the card roughly half-empty even after RPi OS Lite, which keeps a large pool
    # of free blocks for the card's wear-leveling (the headroom point in silicon
    # note 07). Override with BIRDSEED_CLIP_CAP_MB (0 = uncapped).
    cap_mb = int(os.environ.get("BIRDSEED_CLIP_CAP_MB", "16384"))
    cap_bytes = cap_mb * 1_000_000 if cap_mb > 0 else None
    recorder = Recorder(sensor, camera, clips_dir, clip_seconds=10.0, clip_cap_bytes=cap_bytes)
    try:
        recorder.run_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
