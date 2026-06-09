"""The contracts the app depends on — not the implementations.

These are abstract base classes (ABCs). They declare *what* birdseed needs from
its hardware ("wait for motion", "record a clip") without committing to *how*.
Two implementations satisfy them:

    - mock.py     — fakes both, runs anywhere (your Mac, CI). No hardware.
    - hardware.py — drives picamera2 + the GPIO. Pi only. (slice 2b)

The capture loop (recorder.py) talks only to these interfaces, so it never knows
or cares which backend is plugged in. Swap the backend, the loop is untouched.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class MotionSensor(ABC):
    """A source of motion events. Real: a PIR on a GPIO. Mock: a timer."""

    @abstractmethod
    def wait_for_motion(self) -> None:
        """Block until motion is detected, then return."""

    @abstractmethod
    def wait_for_no_motion(self) -> None:
        """Block until the scene is clear (motion has stopped), then return."""


class Camera(ABC):
    """Records video clips. Real: the VideoCore H.264 encoder via picamera2.
    Mock: writes a tiny placeholder file."""

    @abstractmethod
    def record_clip(self, path: Path, duration_s: float) -> Path:
        """Record ``duration_s`` seconds of video to ``path``.

        Returns the path actually written. (A fixed-duration clip on each trigger
        is the MVP; later we can follow motion / add pre-roll from a ring buffer.)
        """
