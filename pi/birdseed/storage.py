"""Phase 4: the storage cap — a byte-bounded ring buffer over the clips dir.

An unattended feeder records forever; an SD card does not. Without a bound the
card fills, and once it's full the *writes start failing* — the recorder silently
stops saving clips. So after each new clip the recorder asks this module to evict
the oldest clips until the directory is back under a size cap. Newest in, oldest
out: a ring buffer, bounded by bytes because bytes are what the card runs out of.

This is pure mechanism and pure Python — no camera, no GPIO, no policy. The *cap
value* is policy and lives in the entry point (run.py); how to enforce it lives
here. That keeps this function trivially testable on the Mac with throwaway files.

Pruning is the *writer's* job, deliberately: the serving layer (server.py) is
read-only and never deletes what it's showing. One owner for destructive acts.
"""

from __future__ import annotations

from pathlib import Path

# We only ever touch our own clips. A stray file in the dir is left alone — we
# never delete something we didn't write.
CLIP_GLOB = "clip_*.mp4"


def enforce_size_cap(clips_dir: Path, cap_bytes: int) -> list[Path]:
    """Delete oldest clips until ``clips_dir`` holds <= ``cap_bytes``.

    "Oldest" is by *filename*, not mtime: the recorder stamps the capture time
    into the name (clip_YYYYMMDD_HHMMSS.mp4), zero-padded, so a plain sort is
    chronological — and it's the same source of truth the server reads for
    display. mtime can drift on a copy/rsync; the name can't, which is what we
    want before a destructive delete.

    We never delete the single newest clip, even if it alone exceeds the cap —
    deleting the clip we just captured would be absurd. Returns the paths deleted
    (newest-evicted last), so the caller can log what went.
    """
    clips = sorted(clips_dir.glob(CLIP_GLOB))  # name sort == oldest first
    total = sum(p.stat().st_size for p in clips)
    deleted: list[Path] = []

    # Stop when under cap, or when only the newest clip remains.
    while total > cap_bytes and len(clips) > 1:
        oldest = clips.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink()
        # The clip's poster JPEG rides along. Thumbnails are ~30 KB next to
        # ~6 MB clips, so they aren't worth counting toward the cap — but an
        # orphaned poster with no clip behind it is just litter.
        oldest.with_suffix(".jpg").unlink(missing_ok=True)
        deleted.append(oldest)

    return deleted
