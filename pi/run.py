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
    clips_dir = Path(__file__).parent / "clips"
    recorder = Recorder(sensor, camera, clips_dir, clip_seconds=10.0)
    try:
        recorder.run_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
