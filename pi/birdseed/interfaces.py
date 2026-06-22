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
    def wait_for_motion(self, timeout: float | None = None) -> bool:
        """Block until motion is detected. Return True on motion.

        With a ``timeout``, give up after that many seconds and return False
        instead of blocking forever. The recorder uses the timeout to come up
        for air between waits and service web commands (snapshot, refocus) —
        otherwise a quiet feeder would never check for them.
        """

    @abstractmethod
    def wait_for_no_motion(self) -> None:
        """Block until the scene is clear (motion has stopped), then return."""


class Camera(ABC):
    """Records video clips, and (for the settings tab) takes stills + focuses.
    Real: the VideoCore H.264 encoder via picamera2. Mock: placeholder files."""

    @abstractmethod
    def record_clip(self, path: Path, duration_s: float) -> Path:
        """Record ``duration_s`` seconds of video to ``path``.

        Returns the path actually written. (A fixed-duration clip on each trigger
        is the MVP; later we can follow motion / add pre-roll from a ring buffer.)
        """

    @abstractmethod
    def apply_settings(self, settings: dict) -> None:
        """Adopt new settings (focus, bitrate, rotation, clip length).

        Called by the recorder while the camera is idle between clips, so a
        change that needs a reconfigure (rotation) can happen safely.
        """

    @abstractmethod
    def capture_still(self, path: Path, lens_position: float | None = None) -> dict:
        """Grab one JPEG to ``path``, optionally at a specific focus.

        ``lens_position`` is in dioptres (1/metres); None leaves focus as-is.
        Returns focus telemetry: {lens_position, focus_fom, af_state}. This is
        the workhorse of the focus-calibration UI — adjust, snapshot, read the
        sharpness score, repeat.
        """

    @abstractmethod
    def autofocus(self) -> dict:
        """Run a single autofocus sweep and return the converged telemetry.

        Used once at install to discover the right lens position for the perch,
        which then gets saved as the fixed manual focus.
        """
