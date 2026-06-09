"""The dumb Pi's entire job, in one loop.

Wait for motion -> record a clip -> wait for the scene to clear -> repeat.
That's it. No classification, no upload. This is the whole 'detect and save'
mandate, and it talks only to the interfaces, so it runs identically against the
mocks (laptop) or the real drivers (Pi).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .interfaces import Camera, MotionSensor


class Recorder:
    def __init__(
        self,
        sensor: MotionSensor,
        camera: Camera,
        clips_dir: Path,
        clip_seconds: float = 10.0,
    ):
        self.sensor = sensor
        self.camera = camera
        self.clips_dir = Path(clips_dir)
        self.clip_seconds = clip_seconds
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    def _next_clip_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.clips_dir / f"clip_{stamp}.h264"

    def run_forever(self) -> None:
        print(f"birdseed recorder up. clips -> {self.clips_dir}/  (Ctrl-C to stop)")
        while True:
            self.sensor.wait_for_motion()
            path = self._next_clip_path()
            self.camera.record_clip(path, self.clip_seconds)
            print(f"saved {path.name}")
            self.sensor.wait_for_no_motion()
