"""Fake hardware, so the whole pipeline runs with no Pi attached.

This is what lets us develop birdseed's logic on a laptop. The mocks honour the
exact same interfaces the real drivers will, so the capture loop can't tell them
apart — now including stills and (fake) autofocus, so the settings tab and its
focus-calibration flow are fully exercisable on the Mac.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from .interfaces import Camera, MotionSensor

# A tiny valid JPEG (a dark brown 320x180 frame), so the snapshot/focus UI has a
# real image to render on the laptop where there's no camera. Decodes in any
# browser; it just isn't a bird.
_PLACEHOLDER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjI4LjEwMQD/2wBDAAgEBAQEBAUFBQUFBQYGBgYG"
    "BgYGBgYGBgYHBwcICAgHBwcGBgcHCAgICAkJCQgICAgJCQoKCgwMCwsODg4RERT/xABNAAEBAAAAAAAA"
    "AAAAAAAAAAAABwEBAQEAAAAAAAAAAAAAAAAAAAMEEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAAAAAAAAAA"
    "AAAAAAAA/8AAEQgAtAFAAwEiAAIRAAMRAP/aAAwDAQACEQMRAD8Al4DKuAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//9k="
)


class MockMotionSensor(MotionSensor):
    """Fires 'motion' on a timer instead of reading a real PIR.

    Honours the wait_for_motion timeout so the recorder's command-polling loop
    behaves the same against the mock as against the real PIR. Motion is rare on
    purpose (every interval_s), so most loops are quiet — which is exactly when
    the recorder services web commands, the path we want to test.
    """

    def __init__(self, interval_s: float = 30.0, motion_duration_s: float = 2.0):
        self.interval_s = interval_s          # quiet time between fake triggers
        self.motion_duration_s = motion_duration_s  # how long fake motion lasts
        self._waited = 0.0

    def wait_for_motion(self, timeout: float | None = None) -> bool:
        slice_s = self.interval_s - self._waited if timeout is None else min(
            timeout, self.interval_s - self._waited
        )
        time.sleep(max(slice_s, 0))
        self._waited += max(slice_s, 0)
        if self._waited >= self.interval_s:
            self._waited = 0.0
            print("[mock-pir] motion!")
            return True
        return False

    def wait_for_no_motion(self) -> None:
        time.sleep(self.motion_duration_s)
        print("[mock-pir] clear")


class MockCamera(Camera):
    """Pretends to record, then writes a tiny placeholder file."""

    def __init__(self):
        self._lens_position = 10.0

    def record_clip(self, path: Path, duration_s: float) -> Path:
        print(f"[mock-cam] recording {duration_s:.0f}s -> {path.name}")
        time.sleep(duration_s)  # stand in for the real recording time
        path.write_text(f"mock clip ({duration_s:.0f}s)\n")
        return path

    def apply_settings(self, settings: dict) -> None:
        self._lens_position = settings.get("lens_position", self._lens_position)

    def capture_still(self, path: Path, lens_position: float | None = None) -> dict:
        if lens_position is not None:
            self._lens_position = lens_position
        path.write_bytes(_PLACEHOLDER_JPEG)
        # Fake a focus-figure-of-merit that peaks at the configured perch (~10
        # dioptres), so the calibration UI shows a believable sharpness curve.
        fom = max(0, 1000 - int(abs(self._lens_position - 10.0) * 120))
        print(f"[mock-cam] still -> {path.name} (lens {self._lens_position:.1f})")
        return {"lens_position": self._lens_position, "focus_fom": fom, "af_state": "idle"}

    def autofocus(self) -> dict:
        time.sleep(0.5)  # stand in for the AF sweep
        self._lens_position = 10.0
        print("[mock-cam] autofocus -> lens 10.0")
        return {"lens_position": 10.0, "focus_fom": 1000, "af_state": "focused"}
