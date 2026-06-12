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

import subprocess

from gpiozero import MotionSensor as _GzMotionSensor
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput

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

    Recording is two steps on purpose. During capture the encoder's bytes go
    straight to a raw .h264 file (FileOutput — pure python, no subprocess).
    Only after the clip ends does ffmpeg repackage it into .mp4 (stream copy,
    no re-encode). We used to mux live through FfmpegOutput instead, and it
    was a bug factory: it pipes frames to an ffmpeg subprocess started with
    -use_wallclock_as_timestamps, so frames are stamped when ffmpeg *reads*
    them, not when the sensor captured them. While ffmpeg boots (seconds, on
    a Zero 2 W) frames pile up in the pipe and drain with garbage timing —
    every clip opened with a stutter-then-freeze, and the boot time was
    silently eaten out of the clip's duration. Raw H.264 has no timestamps
    at all, so the after-the-fact remux stamps a perfectly uniform FPS — and
    there's no subprocess in the capture path left to hiccup. See note 05.
    """

    FPS = 30

    def __init__(
        self,
        encode_size: tuple[int, int] = (1920, 1080),
        sensor_size: tuple[int, int] = (2304, 1296),
        bitrate: int = 8_000_000,
        # The camera is currently mounted upside-down, so flip by default.
        # This is the ISP reading the sensor in the other direction — free
        # (no CPU, no quality loss) and baked into the clip bytes, unlike
        # the website's flip-view button, which is per-viewer cosmetics.
        # Revisit when the enclosure fixes the final mounting.
        rotate_180: bool = True,
    ):
        self._picam2 = Picamera2()
        config = self._picam2.create_video_configuration(
            main={"size": encode_size},
            transform=Transform(hflip=rotate_180, vflip=rotate_180),
            # Pin the full-FoV binned sensor mode; without this the pipeline may
            # pick the narrower cropped mode to match 1080p and lose field of view.
            sensor={"output_size": sensor_size, "bit_depth": 10},
            # Pin the frame cadence (this is also the video-config default).
            # The remux below stamps the .mp4 at FPS, so it must be explicit
            # here rather than left to whatever the sensor mode feels like.
            controls={"FrameDurationLimits": (1_000_000 // self.FPS,) * 2},
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
        raw = path.with_suffix(".h264")
        # Start the camera first and let it warm up BEFORE attaching the
        # encoder, so auto-exposure has settled by the first recorded frame.
        # The camera still stops between clips — it only draws power while a
        # clip is being recorded, which is the deal we want for solar later.
        self._picam2.start()
        try:
            time.sleep(self.WARMUP_S)
            self._picam2.start_encoder(encoder, FileOutput(str(raw)))
            try:
                time.sleep(duration_s)
            finally:
                self._picam2.stop_encoder()
        finally:
            # Always stop, even on Ctrl-C mid-clip, so the camera is released
            # for the next run. An interrupted recording otherwise locks it.
            self._picam2.stop()
        self._remux(raw, path)
        return path

    def _remux(self, raw: Path, path: Path) -> None:
        """Repackage raw H.264 into .mp4: stream copy, uniform FPS timestamps.

        Writes to a .part file and renames at the end so the server (which
        globs *.mp4) can never list a half-written clip. The raw file is
        only deleted on success — if ffmpeg ever fails, the bytes survive
        on disk for a post-mortem.

        +faststart moves the moov atom (the mp4's index) to the front of the
        file. Browsers need the moov before they can show anything, and with
        it at the back every gallery card costs range-request gymnastics into
        the tail of a file on a slow SD card. One flag, one extra rewrite
        pass, while nothing else is happening.
        """
        part = path.with_suffix(".mp4.part")
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-framerate", str(self.FPS), "-i", str(raw),
             "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(part)],
            check=True,
        )
        # Poster frame for the gallery: one JPEG, ~30 KB, so the website can
        # show a grid of <img> instead of opening a video stream per clip.
        # Grabbed 1 s in (the trigger's subject should be in frame by then).
        # Best-effort on purpose: a clip without a poster beats no clip.
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-ss", "1", "-i", str(part),
             "-frames:v", "1", "-vf", "scale=480:-2", str(path.with_suffix(".jpg"))],
            check=False,
        )
        part.rename(path)
        raw.unlink()
