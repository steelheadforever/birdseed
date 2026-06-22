"""The control-plane interface between the two processes — files on disk.

birdseed has always had exactly one shared interface between its halves: the
clips directory. The recorder writes it, the server reads it, and neither
imports the other. Adding a settings tab needs a *second* such seam — a way for
the server (which owns no hardware and runs in a venv without picamera2) to ask
the recorder (sole owner of the camera) to change focus or take a snapshot,
without either process reaching into the other.

So we keep the pattern instead of breaking it: a small state directory of JSON
files and one JPEG. The server writes desired *settings* and posts *commands*;
the recorder reads settings, executes commands between clips, and writes results
+ telemetry back. The camera stays owned by one process, exactly like deletion
stays owned by one process. This module is the only thing both sides import for
that seam, and it's pure file I/O — no hardware, testable anywhere.

Files in the state dir:
    settings.json        desired config (focus, clip length, bitrate, rotation)
    command.json         a one-shot request (snapshot / autofocus); recorder
                         consumes it (deletes) and writes a result
    command_result.json  the outcome of the last command, by id
    camera.json          last-known camera/focus telemetry, for the server
    snapshot.jpg         the most recent still from a snapshot command
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Mirrors the clips-dir override in server.py / run.py so tests and the two
# services can all point at the same place.
_PI_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("BIRDSEED_STATE_DIR", _PI_DIR / "state"))

SETTINGS_FILE = STATE_DIR / "settings.json"
COMMAND_FILE = STATE_DIR / "command.json"
RESULT_FILE = STATE_DIR / "command_result.json"
CAMERA_FILE = STATE_DIR / "camera.json"
SNAPSHOT_FILE = STATE_DIR / "snapshot.jpg"

# The one place defaults live. lens_position is in dioptres (1/metres), so 10.0
# means focus at 0.10 m — the ~10 cm perch distance the feeder is built around,
# and right at the Module 3's close-focus limit. clip_seconds/bitrate match the
# values the recorder used before settings existed, so a fresh install behaves
# identically until someone changes something.
DEFAULTS: dict = {
    "lens_position": 10.0,   # dioptres; 0.0 = infinity, ~10 = 10 cm (the limit)
    "clip_seconds": 10.0,
    "bitrate": 8_000_000,
    "rotate_180": True,      # camera is mounted upside-down (see hardware.py)
}


def _read_json(path: Path) -> dict | None:
    """Read a JSON object, or None if it's absent or mid-write/corrupt.

    Best-effort on purpose: these files are written by one process and read by
    another, so a reader can catch a half-written file. Returning None and
    trying again next tick is always safe; raising would crash a loop.
    """
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None


def _write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: full file to a temp name, then rename.

    rename(2) is atomic on the same filesystem, so a reader never sees a
    partial object — it sees either the old file or the whole new one.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)


def load_settings() -> dict:
    """Current settings, with any missing keys filled from DEFAULTS."""
    return {**DEFAULTS, **(_read_json(SETTINGS_FILE) or {})}


def save_settings(settings: dict) -> dict:
    """Persist settings (merged onto current) and return the saved result."""
    merged = {**load_settings(), **settings}
    _write_json(SETTINGS_FILE, merged)
    return merged


def post_command(action: str, params: dict | None = None) -> int:
    """Queue a one-shot camera command for the recorder. Returns its id.

    The id is just a monotonically-bumped integer the client polls on, so it
    can tell "my command finished" from "a previous command's stale result."
    """
    prev = _read_json(COMMAND_FILE) or _read_json(RESULT_FILE) or {}
    cmd_id = int(prev.get("id", 0)) + 1
    _write_json(COMMAND_FILE, {"id": cmd_id, "action": action, "params": params or {}})
    return cmd_id


def take_command() -> dict | None:
    """Claim the pending command (read then delete), or None if there isn't one.

    Delete-on-read means the recorder runs each command exactly once even though
    it polls the file repeatedly.
    """
    cmd = _read_json(COMMAND_FILE)
    if cmd is not None:
        COMMAND_FILE.unlink(missing_ok=True)
    return cmd


def write_result(result: dict) -> None:
    _write_json(RESULT_FILE, result)


def read_result() -> dict | None:
    return _read_json(RESULT_FILE)


def write_camera_state(camera: dict) -> None:
    _write_json(CAMERA_FILE, camera)


def read_camera_state() -> dict | None:
    return _read_json(CAMERA_FILE)
