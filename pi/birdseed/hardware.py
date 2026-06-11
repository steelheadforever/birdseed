"""The real drivers. Pi-only — imports picamera2 + gpiozero, which don't exist
on the Mac. run.py only imports this module when it detects a real Pi, so the
mock path on a laptop never touches these.

Both classes satisfy the same interfaces as the mocks (interfaces.py), so the
Recorder loop is byte-for-byte identical regardless of which is plugged in.

On Raspberry Pi OS, picamera2 and gpiozero ship preinstalled (via apt) — no pip.
"""

from __future__ import annotations

import time
from pathlib import Path

from gpiozero import MotionSensor as _GzMotionSensor
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

from .interfaces import Camera, MotionSensor

PIR_GPIO = 17  # BCM numbering — physical pin 11, where we wired the AM312 OUT


class GpioPirSensor(MotionSensor):
    """The AM312 on GPIO17. gpiozero does the edge detection for us; we just
    expose the same blocking wait_* calls the loop expects."""

    def __init__(self, pin: int = PIR_GPIO):
        self._pir = _GzMotionSensor(pin)

    def wait_for_motion(self) -> None:
        self._pir.wait_for_motion()

    def wait_for_no_motion(self) -> None:
        self._pir.wait_for_no_motion()


class Picamera2Camera(Camera):
    """Records H.264 via the VideoCore hardware encoder.

    Encoder output is 1920x1080 (the encoder's ceiling — see silicon note 04),
    but the sensor is pinned to its full-FoV 2304x1296 mode, so the ISP
    *downscales* rather than crops. Wide view in, encodable frame out.

    Output goes through FfmpegOutput, which muxes the hardware H.264 straight
    into a real .mp4 container (no re-encode — just repackaging, with the correct
    framerate baked in). Plays in QuickTime / phone / browser. See note 05.
    """

    def __init__(
        self,
        encode_size: tuple[int, int] = (1920, 1080),
        sensor_size: tuple[int, int] = (2304, 1296),
        bitrate: int = 8_000_000,
    ):
        self._picam2 = Picamera2()
        config = self._picam2.create_video_configuration(
            main={"size": encode_size},
            # Pin the full-FoV binned sensor mode; without this the pipeline may
            # pick the narrower cropped mode to match 1080p and lose field of view.
            sensor={"output_size": sensor_size, "bit_depth": 10},
        )
        self._picam2.configure(config)
        self._bitrate = bitrate

    # How long the sensor pipeline + auto-exposure need after a cold start
    # before frames arrive at a steady cadence. Measured on real clips: the
    # first ~0.7 s of frames came out sparse and irregularly timestamped,
    # which played back as a stutter-then-freeze at the top of every clip.
    WARMUP_S = 1.5

    def record_clip(self, path: Path, duration_s: float) -> Path:
        encoder = H264Encoder(bitrate=self._bitrate)
        # Start the camera first and let it warm up BEFORE attaching the
        # encoder, so the ragged spin-up frames are never recorded and the
        # clip is duration_s of steady video (previously the camera started
        # inside start_recording, so warmup ate ~1.5 s of the clip). The
        # camera still stops between clips — it only draws power while a
        # clip is being recorded, which is the deal we want for solar later.
        self._picam2.start()
        try:
            time.sleep(self.WARMUP_S)
            self._picam2.start_encoder(encoder, FfmpegOutput(str(path)))
            try:
                time.sleep(duration_s)
            finally:
                self._picam2.stop_encoder()
        finally:
            # Always stop, even on Ctrl-C mid-clip, so the camera is released
            # for the next run. An interrupted recording otherwise locks it.
            self._picam2.stop()
        return path
