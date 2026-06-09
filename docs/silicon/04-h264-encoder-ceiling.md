# 04 — The hardware H.264 encoder and its 1080p ceiling

_Phase 2. Why `rpicam-vid` failed at 2304×1296 but records fine at 1080p — and it
was never about memory._

## The symptom

`rpicam-vid` at **2304×1296** died with:

```
Overriding H.264 level 4.2
...
bcm2835-codec: bcm2835_codec_start_streaming: Failed enabling i/p port, ret -3
```

…while **1280×720** and **1920×1080** record fine. Two wrong guesses got ruled out
*by measurement* first:

- **CMA exhaustion?** No — `CmaFree` was 132 MB of 256 MB. Plenty.
- **gpu_mem too small?** No — bumping it 64 → 128 MB changed nothing.

The wall was in the **encoder silicon**, not memory.

## The real cause: H.264 levels and macroblocks

The VideoCore IV has a **dedicated hardware H.264 encoder block** (exposed to Linux
as a V4L2 device, `/dev/video11`, via the `bcm2835-codec` driver). It does the
compression so the ARM cores don't have to.

H.264 defines **"levels"** — a number capping the max **frame size**, frame rate,
and bitrate. Frame size is measured in **macroblocks** (16×16-pixel tiles), not
pixels. This encoder tops out at **Level 4.2**, whose ceiling is **MaxFS = 8704
macroblocks per frame.**

| Resolution | Macroblocks (⌈W/16⌉ × ⌈H/16⌉) | vs. 8704 cap |
|---|---|---|
| 1280×720 | 80 × 45 = **3,600** | ✅ fits easily |
| 1920×1080 | 120 × 68 = **8,160** | ✅ fits (just under) |
| 2304×1296 | 144 × 81 = **11,664** | ❌ exceeds → port refuses to enable |

So the driver pinned the encoder to its max level (4.2), the ~3 MP frame *still*
didn't fit, the input port refused to come up, and streaming failed. 720p worked
because 3,600 ≪ 8,704. **Pure silicon limit.**

## The deeper lesson: the sensor can outrun the encoder

These are two different blocks inside the SoC with different limits:

- The **IMX708 sensor** can produce up to 4608×2592, and a 2304×1296 binned mode.
- The **H.264 encoder** can't compress anything above ~1080p.

A pipeline is only as capable as its **tightest stage**. The sensor producing a
frame doesn't mean the encoder can swallow it.

The fix costs us nothing: the full-FoV sensor mode (2304×1296) is **16:9**, and so
is 1920×1080. The **ISP downscales** the full frame to 1080p before the encoder —
**full field of view preserved, no cropping.** Wide view *and* an encodable frame.

## Decision for birdseed (supersedes note 02)

**Encode clips at 1920×1080, ISP-downscaled from the full-FoV 2304×1296 sensor
mode.** 1080p is the hardware ceiling and is plenty — bird-ID on the phone
(phase 2) downsamples much further anyway. Reserve the full 4608×2592 only for
still snapshots, which go through the JPEG path, not the H.264 encoder.

## Why hardware encoding is the whole game

Measured: a 5-second 1080p clip = **5.5 MB** (~8.8 Mbit/s). The uncompressed
equivalent is ~1.3 GB. That ~99.5% reduction happened **in the GPU encoder block,
in real time, with the ARM cores idle.** This is exactly why a tiny Pi can be a
video recorder — and why "keep the Pi dumb" works: the expensive part is offloaded
to fixed-function silicon.

## Terms worth keeping

- **Macroblock** — 16×16-pixel tile; the unit H.264 levels are measured in.
- **H.264 level** — caps max frame size / rate / bitrate. VideoCore IV = Level 4.2.
- **MaxFS** — max frame size in macroblocks for a level (4.2 → 8704).
- **V4L2 M2M** — the memory-to-memory device interface the encoder is exposed
  through (`/dev/video11`).
- **Elementary stream** — raw `.h264` with no container; muxed into `.mp4` later.

## Open threads

- Bitrate / quality tuning (`--bitrate`) for the storage budget.
- Keyframe (I-frame) interval — affects clip seekability and file size.
- Muxing the elementary stream to `.mp4` (Phase 4 storage).
