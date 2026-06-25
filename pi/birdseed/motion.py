"""Did anything actually happen in this clip? — the cheap 'confirm' step.

The PIR is dumb and untunable: it fires on any IR change — a bird, but also
wind stirring warm air, the board flexing in the sun, a cloud's shadow. So a lot
of clips are 'empty motion'. The architecture always planned for a software
confirm after the dumb trigger; this is it.

The method is deliberately the cheapest thing that works: decode the clip small
and grey and ask ffmpeg's scene-change detector (scdet) how much each frame
differs from the one before. A still scene scores near zero; a bird moving
through frame spikes it. We take the peak — one real moment of motion is enough
to keep a clip. No numpy, no OpenCV, one ffmpeg pass over a 320x180 decode, a
couple seconds of idle CPU on a Zero 2 W.

What this CAN'T do, and we shouldn't pretend otherwise: if the camera itself is
shaking (wind on an unmounted board), the whole frame changes and the score is
high — a real subject and a wobbling camera look the same to frame differencing.
That false positive is mechanical; the enclosure's rigid mount is its fix. The
score still diagnoses which problem we have: empty clips that score LOW are
PIR-on-nothing (this filters them); empty clips that score HIGH are camera shake
(this won't, and now we know).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# scdet attaches lavfi.scd.score (0..100ish) to frames; metadata=print emits it.
_SCORE_RE = re.compile(r"scd\.score=\s*([\d.]+)")


def score_clip(path: Path, sample_height: int = 180) -> float | None:
    """Peak frame-to-frame change across the clip, or None if it can't score.

    Returns the maximum scene-change score (bigger = more motion). None means
    ffmpeg couldn't analyze the file (not a real video — e.g. a mock clip in
    tests, or a corrupt capture); callers MUST treat None as 'keep', never as
    'empty', so a scoring failure can never silently delete a real clip.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        # Downscale before diffing: faster, and it averages out sensor noise so
        # a still-but-grainy night scene doesn't read as motion. Width -2 keeps
        # the aspect ratio (and stays even, which the scaler requires).
        "-vf", f"scale=-2:{sample_height},scdet=threshold=0,metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    scores = [float(m) for m in _SCORE_RE.findall(proc.stdout + proc.stderr)]
    if not scores:
        return None
    return max(scores)
