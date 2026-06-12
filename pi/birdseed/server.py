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

What it deliberately does NOT do: delete clips. Enforcing the storage cap is the
*writer's* job and will live in the recorder (next slice). A read-only view does
not prune what it is looking at.

The HTML page (web/index.html) is dumb too: it fetches /api/clips and renders the
gallery in the browser. The Pi serves data + static files; the client does the
rendering. Same "dumb device, smart client" split as bird-ID-on-the-phone.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# server.py lives at pi/birdseed/server.py, so parent.parent is pi/.
_PI_DIR = Path(__file__).resolve().parent.parent
CLIPS_DIR = Path(os.environ.get("BIRDSEED_CLIPS_DIR", _PI_DIR / "clips"))
WEB_DIR = _PI_DIR / "web"

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


@app.get("/")
def index() -> FileResponse:
    """The gallery page itself — a static file the browser renders."""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")
