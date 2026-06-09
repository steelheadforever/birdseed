"""Fake hardware, so the whole pipeline runs with no Pi attached.

This is what lets us develop birdseed's logic on a laptop. The mocks honour the
exact same interfaces the real drivers will, so the capture loop can't tell them
apart.
"""

from __future__ import annotations

import time
from pathlib import Path

from .interfaces import Camera, MotionSensor


class MockMotionSensor(MotionSensor):
    """Fires 'motion' on a timer instead of reading a real PIR."""

    def __init__(self, interval_s: float = 5.0, motion_duration_s: float = 2.0):
        self.interval_s = interval_s          # quiet time between fake triggers
        self.motion_duration_s = motion_duration_s  # how long fake motion lasts

    def wait_for_motion(self) -> None:
        time.sleep(self.interval_s)
        print("[mock-pir] motion!")

    def wait_for_no_motion(self) -> None:
        time.sleep(self.motion_duration_s)
        print("[mock-pir] clear")


class MockCamera(Camera):
    """Pretends to record, then writes a tiny placeholder file."""

    def record_clip(self, path: Path, duration_s: float) -> Path:
        print(f"[mock-cam] recording {duration_s:.0f}s -> {path.name}")
        time.sleep(duration_s)  # stand in for the real recording time
        path.write_text(f"mock clip ({duration_s:.0f}s)\n")
        return path
