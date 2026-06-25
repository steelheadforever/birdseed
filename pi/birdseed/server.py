"""Phase 5: serving. A strictly read-only window onto the clips directory.

The recorder (recorder.py) *writes* clips. This server only ever *reads* them.
The two share nothing but the directory on disk: the server imports no hardware,
knows nothing about the camera or the PIR, and never touches the recorder. That
decoupling is the whole point of this slice — the clips dir is the interface
between a dumb producer and a dumb consumer, the same way interfaces.py is the
seam between the capture loop and the hardware. What falls out of it for free:

  - No picamera2 / gpiozero import here, so this module runs byte-for-byte
    identically on the Mac and on the Pi, and lives happily in its own venv.
  - On the Pi it's its own process (its own systemd service). Capture can crash
    and restart without disturbing serving, and vice-versa.

What it deliberately does NOT do: delete clips, or touch the camera. Enforcing
the storage cap is the *writer's* job (the recorder); driving the lens is too.
The settings tab (added later) doesn't change that — when the UI adjusts focus
or asks for a snapshot, the server only *writes a request* to the state dir
(see state.py) and the recorder, sole owner of the camera, carries it out. So
the server still imports no picamera2 and still never prunes or records. It
gained a control plane, not hardware.

The HTML page (web/index.html) is dumb too: it fetches /api/clips and renders the
gallery in the browser. The Pi serves data + static files; the client does the
rendering. Same "dumb device, smart client" split as bird-ID-on-the-phone.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import state, telemetry

# server.py lives at pi/birdseed/server.py, so parent.parent is pi/.
_PI_DIR = Path(__file__).resolve().parent.parent
CLIPS_DIR = Path(os.environ.get("BIRDSEED_CLIPS_DIR", _PI_DIR / "clips"))
WEB_DIR = _PI_DIR / "web"

# The same cap policy run.py uses, read here only so /api/health can show how
# full the ring buffer is. The server still never enforces it.
_cap_mb = int(os.environ.get("BIRDSEED_CLIP_CAP_MB", "16384"))
CLIP_CAP_BYTES = _cap_mb * 1_000_000 if _cap_mb > 0 else None

app = FastAPI(title="birdseed", description="A dumb Pi serving its own bird clips.")


def _human_size(n: int) -> str:
    """Bytes -> a friendly string. Clips are MB-scale; keep it simple."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _recorded_at(name: str) -> str | None:
    """Pull the capture time out of a clip_YYYYMMDD_HHMMSS.mp4 filename.

    The recorder stamps the time into the name, so we don't need a database —
    the filename *is* the metadata. Returns an ISO-8601 string, or None if the
    name doesn't match (the browser falls back to showing nothing for the time).
    """
    stem = Path(name).stem  # clip_20260608_225755
    try:
        dt = datetime.strptime(stem, "clip_%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return dt.isoformat()


@app.get("/api/days")
def list_days() -> list[dict]:
    """Which days have clips, and how many — newest day first.

    This is the gallery's table of contents. The client fetches this (tiny),
    renders a section per day, and only pulls a day's clip list when it's
    actually opened. Still a pure directory read: the date lives in the
    filename, so 'group by day' is 'group by name prefix'.
    """
    if not CLIPS_DIR.is_dir():
        return []
    counts: dict[str, int] = {}
    for path in CLIPS_DIR.glob("clip_*.mp4"):
        iso = _recorded_at(path.name)
        if iso is not None:
            day = iso[:10]  # YYYY-MM-DD
            counts[day] = counts.get(day, 0) + 1
    return [{"day": d, "count": c} for d, c in sorted(counts.items(), reverse=True)]


@app.get("/api/clips")
def list_clips(day: str | None = None) -> list[dict]:
    """Clips on disk, newest first — optionally just one day's (?day=YYYY-MM-DD).

    The day filter is a glob prefix, not a scan-and-compare: the capture time
    is stamped into the filename, so one day's clips share a name prefix and
    the directory read never touches the other days' files at all.
    """
    if not CLIPS_DIR.is_dir():
        return []
    prefix = "clip_"
    if day is not None:
        try:
            prefix = datetime.strptime(day, "%Y-%m-%d").strftime("clip_%Y%m%d_")
        except ValueError:
            raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
    clips = []
    for path in CLIPS_DIR.glob(prefix + "*.mp4"):
        stat = path.stat()
        thumb = path.with_suffix(".jpg")
        clips.append(
            {
                "name": path.name,
                "recorded_at": _recorded_at(path.name),
                "size_bytes": stat.st_size,
                "size_human": _human_size(stat.st_size),
                # The poster JPEG's name, or null — clips from before posters
                # existed don't have one, and the client shows a placeholder.
                "thumb": thumb.name if thumb.is_file() else None,
            }
        )
    # Newest first. recorded_at is None-safe to sort on via the filename, which
    # sorts chronologically anyway because the timestamp is zero-padded.
    clips.sort(key=lambda c: c["name"], reverse=True)
    return clips


@app.get("/clips/{name}")
def get_clip(name: str) -> FileResponse:
    """Serve one clip's bytes.

    FileResponse honours the browser's `Range:` header — it returns 206 Partial
    Content for a requested byte range instead of the whole file. That is what
    lets a <video> element scrub/seek a 50 MB clip without downloading all of it
    (see docs/silicon/06). We do the path-traversal guard ourselves: resolve the
    requested name and refuse anything that isn't a real .mp4 sitting directly in
    the clips dir, so `../../etc/passwd` can't escape the directory.
    """
    candidate = (CLIPS_DIR / name).resolve()
    if candidate.parent != CLIPS_DIR.resolve() or candidate.suffix != ".mp4" or not candidate.is_file():
        raise HTTPException(status_code=404, detail="no such clip")
    return FileResponse(candidate, media_type="video/mp4")


@app.get("/thumbs/{name}")
def get_thumb(name: str) -> FileResponse:
    """Serve one clip's poster JPEG. Same traversal guard as the clips route."""
    candidate = (CLIPS_DIR / name).resolve()
    if candidate.parent != CLIPS_DIR.resolve() or candidate.suffix != ".jpg" or not candidate.is_file():
        raise HTTPException(status_code=404, detail="no such thumbnail")
    return FileResponse(candidate, media_type="image/jpeg")


# --------------------------------------------------------------------------
# Settings tab: device health (read), settings (read/write), and camera/system
# commands (write a request; the recorder executes camera ones). The server
# still touches neither clips nor camera directly — see the module docstring.
# --------------------------------------------------------------------------

@app.get("/api/health")
def get_health() -> dict:
    """Everything the settings dashboard shows: Wi-Fi, power, temp, storage,
    uptime/services/version, and the camera's last-known focus state."""
    return telemetry.health(CLIPS_DIR, CLIP_CAP_BYTES)


@app.get("/api/settings")
def get_settings() -> dict:
    """The current desired settings (focus, clip length, bitrate, rotation)."""
    return state.load_settings()


# Bounds for the writable settings. Out-of-range values are clamped, not
# rejected, so a slider can't ever wedge the recorder with a bad number.
_SETTING_BOUNDS = {
    "lens_position": (0.0, 10.0),    # dioptres: infinity .. ~10 cm (lens limit)
    "clip_seconds": (1.0, 60.0),
    "bitrate": (1_000_000, 15_000_000),
    "motion_threshold": (0.0, 100.0),  # 0 = keep all; scdet score scale
}


@app.post("/api/settings")
def post_settings(payload: dict = Body(...)) -> dict:
    """Persist settings. The recorder picks them up on its next idle tick."""
    clean: dict = {}
    for key, value in payload.items():
        if key == "rotate_180":
            clean[key] = bool(value)
        elif key in _SETTING_BOUNDS:
            lo, hi = _SETTING_BOUNDS[key]
            try:
                clean[key] = max(lo, min(hi, float(value)))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{key} must be a number")
        # Unknown keys are ignored, not an error — forward-compatible UI.
    return state.save_settings(clean)


_CAMERA_ACTIONS = {"snapshot", "autofocus"}


@app.post("/api/command")
def post_command(payload: dict = Body(...)) -> dict:
    """Queue a camera command for the recorder. Returns an id to poll on.

    The server can't drive the camera (no picamera2, by design), so this just
    drops a request the recorder will run when it's next idle between clips.
    """
    action = payload.get("action")
    if action not in _CAMERA_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {sorted(_CAMERA_ACTIONS)}")
    cmd_id = state.post_command(action, payload.get("params"))
    return {"id": cmd_id, "status": "queued"}


@app.get("/api/command/{cmd_id}")
def get_command(cmd_id: int) -> dict:
    """Poll a command's result. 'pending' until the recorder has run it."""
    result = state.read_result()
    if result and int(result.get("id", -1)) == cmd_id:
        return {"status": "done", **result}
    return {"status": "pending", "id": cmd_id}


@app.post("/api/delete")
def post_delete(payload: dict = Body(...)) -> dict:
    """Queue a bulk delete (a day, or everything). Returns an id to poll on.

    Like the camera commands, the server only *requests* — the recorder owns
    deletion and carries it out, so the read-only-for-clips contract holds.
    """
    scope = payload.get("scope")
    if scope not in ("day", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'day' or 'all'")
    params = {"scope": scope}
    if scope == "day":
        day = payload.get("day")
        try:
            datetime.strptime(str(day), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
        params["day"] = day
    return {"id": state.post_command("delete", params), "status": "queued"}


@app.get("/snapshot.jpg")
def get_snapshot() -> FileResponse:
    """The most recent still the recorder captured for the focus UI."""
    if not state.SNAPSHOT_FILE.is_file():
        raise HTTPException(status_code=404, detail="no snapshot yet")
    return FileResponse(state.SNAPSHOT_FILE, media_type="image/jpeg")


_SYSTEM_ACTIONS = {
    # Maps a UI action to the exact command. These are the ONLY commands the
    # sudoers drop-in (pi/systemd/birdseed-sudoers) grants the server NOPASSWD.
    "reboot": ["sudo", "systemctl", "reboot"],
    "restart": ["sudo", "systemctl", "restart", "birdseed.target"],
}


@app.post("/api/system/{action}")
def post_system(action: str) -> dict:
    """Reboot the Pi or restart both services — remote recovery without SSH.

    Returns rather than raising on failure (e.g. missing sudoers, or on the Mac)
    so the UI can show why instead of a generic 500.
    """
    cmd = _SYSTEM_ACTIONS.get(action)
    if not cmd:
        raise HTTPException(status_code=400, detail=f"action must be one of {sorted(_SYSTEM_ACTIONS)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return {"ok": True, "action": action}
        return {"ok": False, "action": action, "error": proc.stderr.strip() or "command failed"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "action": action, "error": str(e)}


@app.get("/")
def index() -> FileResponse:
    """The gallery page itself — a static file the browser renders."""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")
