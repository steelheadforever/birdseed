"""The dumb Pi's entire job, in one loop.

Wait for motion -> record a clip -> wait for the scene to clear -> repeat.
That's it. No classification, no upload. This is the whole 'detect and save'
mandate, and it talks only to the interfaces, so it runs identically against the
mocks (laptop) or the real drivers (Pi).

The one addition beyond detect-and-save: between motion waits the loop services
web commands from the settings tab (take a snapshot, run an autofocus) and picks
up any changed settings. The recorder is the *sole owner of the camera*, so any
request that touches the camera has to be executed here — the server can only
ask. The motion wait has a timeout precisely so a quiet feeder still comes up
for air often enough to answer those requests. See state.py for the seam.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import motion, state
from .interfaces import Camera, MotionSensor
from .storage import enforce_size_cap

# How long to block waiting for motion before looping to service commands and
# re-read settings. Short enough that the settings tab feels responsive; long
# enough that a quiet feeder isn't busy-spinning.
POLL_S = 1.0


class Recorder:
    def __init__(
        self,
        sensor: MotionSensor,
        camera: Camera,
        clips_dir: Path,
        clip_seconds: float = 10.0,
        clip_cap_bytes: int | None = None,
    ):
        self.sensor = sensor
        self.camera = camera
        self.clips_dir = Path(clips_dir)
        self.clip_seconds = clip_seconds
        # None = no cap (fine for dev). On the Pi, run.py supplies a real cap so
        # the card can't fill. The writer prunes; the (read-only) server never does.
        self.clip_cap_bytes = clip_cap_bytes
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        # Motion-confirm state. threshold 0 = keep all (set from settings each
        # loop); the rest is telemetry the settings tab reads back to calibrate.
        self._motion_threshold = 0.0
        self._last_motion_score: float | None = None
        self._filtered_count = 0  # clips discarded as empty, since boot

    def _next_clip_path(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.clips_dir / f"clip_{stamp}.mp4"

    def run_forever(self) -> None:
        print(f"birdseed recorder up. clips -> {self.clips_dir}/  (Ctrl-C to stop)")
        while True:
            # Camera is idle here, so this is the safe moment to adopt settings
            # and run any pending web command.
            self._apply_settings()
            self._handle_command()
            if self.sensor.wait_for_motion(timeout=POLL_S):
                path = self._next_clip_path()
                self.camera.record_clip(path, self.clip_seconds)
                self._confirm_motion(path)  # keep or discard as 'empty motion'
                self._enforce_cap()
                self.sensor.wait_for_no_motion()

    def _confirm_motion(self, path: Path) -> None:
        """Score the just-recorded clip; delete it if it's empty motion.

        Always logs the score (that log IS the calibration data). Deletes only
        when the threshold is armed (>0) and the score is below it — and never
        when scoring failed (score is None), so a bad analysis can't eat a real
        clip. The poster .jpg rides along, like the storage cap's eviction.
        """
        score = motion.score_clip(path)
        self._last_motion_score = score
        thr = self._motion_threshold
        shown = "n/a" if score is None else f"{score:.2f}"
        if score is not None and thr > 0 and score < thr:
            path.unlink(missing_ok=True)
            path.with_suffix(".jpg").unlink(missing_ok=True)
            self._filtered_count += 1
            print(f"discarded {path.name} (motion {shown} < {thr:.2f})")
        else:
            print(f"saved {path.name} (motion {shown})")

    def _apply_settings(self) -> None:
        """Re-read settings, push them to the camera, and publish camera state.

        Cheap enough to do every poll: it's a small JSON read. Keeping it in the
        loop means a setting saved from the web takes effect on the next idle
        tick without any signal plumbing.
        """
        settings = state.load_settings()
        self.clip_seconds = float(settings.get("clip_seconds", self.clip_seconds))
        self._motion_threshold = float(settings.get("motion_threshold", 0.0))
        try:
            self.camera.apply_settings(settings)
        except Exception as e:  # never let a bad setting kill the capture loop
            print(f"  (settings apply failed: {e})")
        state.write_camera_state(
            {
                "lens_position": settings.get("lens_position"),
                "focus_distance_m": (
                    1.0 / settings["lens_position"]
                    if settings.get("lens_position")
                    else None
                ),
                "clip_seconds": self.clip_seconds,
                "bitrate": settings.get("bitrate"),
                "rotate_180": settings.get("rotate_180"),
                # Motion-confirm telemetry, for live calibration in the UI.
                "motion_threshold": self._motion_threshold,
                "last_motion_score": self._last_motion_score,
                "filtered_count": self._filtered_count,
            }
        )

    def _handle_command(self) -> None:
        """Run one queued camera command (snapshot / autofocus), if any."""
        cmd = state.take_command()
        if not cmd:
            return
        action, params, cmd_id = cmd.get("action"), cmd.get("params", {}), cmd.get("id")
        print(f"  command #{cmd_id}: {action} {params}")
        try:
            if action == "snapshot":
                lp = params.get("lens_position")
                focus = self.camera.capture_still(state.SNAPSHOT_FILE, lens_position=lp)
                result = {"id": cmd_id, "action": action, "ok": True, "focus": focus}
            elif action == "autofocus":
                focus = self.camera.autofocus()
                # Persist the discovered focus so clips use it from now on.
                state.save_settings({"lens_position": focus.get("lens_position")})
                result = {"id": cmd_id, "action": action, "ok": True, "focus": focus}
            elif action == "delete":
                # User-initiated bulk delete from the gallery. Deletion is the
                # recorder's job (it owns the storage cap and the motion filter),
                # so the read-only server asks and we carry it out here.
                n = self._delete_clips(params)
                result = {"id": cmd_id, "action": action, "ok": True, "deleted": n}
            else:
                result = {"id": cmd_id, "action": action, "ok": False, "error": "unknown action"}
        except Exception as e:
            result = {"id": cmd_id, "action": action, "ok": False, "error": str(e)}
        state.write_result(result)

    def _delete_clips(self, params: dict) -> int:
        """Delete a day's clips, or all of them. Returns how many were removed.

        scope='all'  -> every clip on disk.
        scope='day'  -> one day (params['day'] = YYYY-MM-DD), matched by the
                        filename prefix, so we never touch another day's files.
        The date is run through strptime before it touches a glob, so nothing
        user-controlled reaches the filesystem path — no traversal possible.
        Each clip's poster .jpg goes with it.
        """
        scope = params.get("scope")
        if scope == "all":
            targets = list(self.clips_dir.glob("clip_*.mp4"))
        elif scope == "day":
            try:
                prefix = datetime.strptime(params.get("day", ""), "%Y-%m-%d").strftime("clip_%Y%m%d_")
            except ValueError:
                return 0
            targets = list(self.clips_dir.glob(prefix + "*.mp4"))
        elif scope == "names":
            # Specific clips picked in the gallery's select mode. Each name is
            # resolved and checked to be a real .mp4 sitting directly in the
            # clips dir (same guard the server uses for serving), so a crafted
            # name like '../../etc/passwd' can't escape and nothing else is hit.
            base = self.clips_dir.resolve()
            targets = []
            for name in params.get("names", []):
                cand = (self.clips_dir / str(name)).resolve()
                if cand.parent == base and cand.suffix == ".mp4" and cand.is_file():
                    targets.append(cand)
        else:
            return 0
        count = 0
        for p in targets:
            p.unlink(missing_ok=True)
            p.with_suffix(".jpg").unlink(missing_ok=True)
            count += 1
        print(f"  deleted {count} clip(s) (scope={scope}, day={params.get('day', '-')})")
        return count

    def _enforce_cap(self) -> None:
        """Evict oldest clips if we're over the size cap. No-op when uncapped."""
        if self.clip_cap_bytes is None:
            return
        for gone in enforce_size_cap(self.clips_dir, self.clip_cap_bytes):
            print(f"  pruned {gone.name} (over {self.clip_cap_bytes // 1_000_000} MB cap)")
