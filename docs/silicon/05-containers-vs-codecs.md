# 05 — Containers vs. codecs: muxing `.h264` into `.mp4`

_Phase 2/4. Why our clips were raw `.h264`, why we want `.mp4`, and why rewrapping
them is cheap while re-encoding would be ruinous._

## Two different things wearing one word ("video file")

- A **codec** (H.264) is *how the pixels are compressed*. The VideoCore hardware
  encoder produced this — it's the expensive, clever part.
- A **container** (MP4, MKV, …) is *the box the compressed stream sits in*. It adds
  framerate/timing, an index for seeking, metadata, and (later) an audio track.

`rpicam-vid -o test.h264` gave us a **raw elementary stream** — codec, no
container. It plays in VLC/ffplay (which can guess), but **not** QuickTime, a
phone, or a browser, because those need the container's index and timing.

## Muxing ≠ transcoding (this is the key distinction)

| | What it does | Cost |
|---|---|---|
| **Mux** (`ffmpeg -c copy`) | Repackage the *already-encoded* H.264 into an MP4 box. No pixels touched. | Cheap, fast, lossless. Fine on the Pi. |
| **Transcode** | *Decode* then *re-encode* the video (e.g. to a new codec/bitrate). | CPU-melting. Never do this on the Pi. |

We only ever **mux**. The hardware already did the hard part; we're just changing
the box.

## The framerate gotcha

A raw `.h264` has **no timing information**. If you mux it after the fact, ffmpeg
*guesses* (defaults to 25 fps) — so a 30 fps clip plays back at the wrong speed.
The fix: mux **at record time**, when the camera's real framerate is known.

That's why birdseed records through picamera2's **`FfmpegOutput`** instead of
`FileOutput`: the hardware encoder's H.264 is piped straight through ffmpeg's
muxer *during* recording, producing a correct `.mp4` in one step — no leftover
raw files, right framerate baked in. (Needs `ffmpeg` installed: `apt install
ffmpeg`. It's still just a stream copy — the CPU stays cheap.)

## The finalization catch (matters for a solar feeder cam)

An MP4's index — the **`moov` atom** — is written when recording **stops
cleanly**. Kill the process mid-clip (Ctrl-C, power loss) and the MP4 can be left
unplayable. Two defenses:

1. Our `record_clip` uses `try/finally` so `stop_recording()` always runs on a
   normal interrupt — the moov atom gets written.
2. **Power loss** is the harder case (the whole system dies). The robust answer is
   a **fragmented MP4** (`-movflags +frag_keyframe+empty_moov`), which writes the
   index incrementally so a half-written file is still playable. Deferred to the
   storage/power phases — noting it here so we don't forget.

## Terms worth keeping

- **Codec** — the compression scheme for the pixels (H.264).
- **Container** — the file format wrapping the stream (MP4).
- **Elementary stream** — codec output with no container (`.h264`).
- **Mux / demux** — pack / unpack streams into / out of a container.
- **moov atom** — MP4's seek index; written on clean stop.

## Open threads

- Switch to fragmented MP4 for crash/power-loss resilience (storage/power phase).
- Do we ever want audio? (No mic on the BOM; skip for now.)
