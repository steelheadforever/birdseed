# 02 — The image sensor: Bayer, two buses, binning vs. cropping

_Phase 1. Decoding what `rpicam-hello --list-cameras` told us about the Camera
Module 3's Sony **IMX708**._

The raw enumeration:

```
0 : imx708 [4608x2592 10-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx708@1a)
    Modes: 'SRGGB10_CSI2P' : 1536x864  [120.13 fps - (768,432)/3072x1728 crop]
                             2304x1296  [56.03 fps  - (0,0)/4608x2592 crop]
                             4608x2592  [14.35 fps  - (0,0)/4608x2592 crop]
```

Nearly every field is a hardware fact. Decoded:

## The sensor is colorblind — Bayer is how it fakes color

- **`4608x2592`** ≈ 11.9 M photosites — the "12 MP" on the box.
- **`10-bit`** — each photosite's analog charge is digitized to **1024 levels**
  by the on-sensor ADC (8-bit would be 256). More levels = more dynamic-range
  headroom for the ISP before it flattens to 8-bit JPEG.
- **`RGGB`** — a photosite only measures **brightness**, not color. To get color,
  a tiny colored filter sits over each one in a repeating **2×2 Bayer tile:
  `R G / G B`**. So a raw frame is a **mosaic of single-color samples**, one
  channel per pixel — not a color image. Reconstructing full RGB (interpolating
  the two missing channels at every pixel) is **demosaicing**, done by the
  VideoCore **ISP**. "10-bit RGGB" is the **raw, pre-ISP** data.
- **Why two greens?** The human eye is most sensitive to green/luminance, so half
  the photosites are green. A perceptual optimization etched into the filter layer.

## A camera has two buses

The device-tree path `/base/soc/i2c0mux/i2c@1/imx708@1a` reveals it:

- **I²C** (sensor at address `0x1a`) — the slow **control** channel. Used to poke
  registers: resolution, exposure, gain, **autofocus**. This is the bus in the path.
- **MIPI CSI-2** — the high-speed **data** channel. The actual pixels scream
  across the differential ribbon pairs in the camera cable. *Not* on I²C.

Control on I²C, pixels on CSI-2 — two separate conversations with one chip.

## Modes: binning vs. cropping, and the fps tradeoff

`SRGGB10_CSI2P` = Bayer RGGB, 10-bit, **CSI-2 packed** (4 pixels bit-packed into
5 bytes, so 10-bit samples don't waste bus bandwidth in padded 16-bit slots).

The `(x,y)/W×H crop` field shows *which part of the sensor* and *how it's
downsized*. Two distinct tricks:

- **Binning** — average adjacent same-color photosites (2×2) into one output
  pixel. Lower resolution, but more light per pixel (less noise), less data,
  faster readout, **full field of view kept**.
- **Cropping** — read only a sub-rectangle of the sensor. Narrower field of view,
  no detail loss in what's read.

| Mode | What it does | Tradeoff |
|------|--------------|----------|
| 1536×864 @ 120 fps | center **2/3 crop** (3072×1728) + 2×2 bin | fastest, **narrower FoV** |
| 2304×1296 @ 56 fps | **full sensor** + 2×2 bin | **full FoV**, half-res, fast |
| 4608×2592 @ 14 fps | full sensor, **no binning** | max detail, slow, data-heavy |

**The rule:** fewer pixels to clock off the sensor → higher frame rate. Full
12 MP is only 14 fps because reading every photosite takes time.

## Decision for birdseed

> **Corrected in [note 04](04-h264-encoder-ceiling.md):** I picked the sensor mode
> here without checking the *encoder's* limit. The hardware H.264 encoder caps at
> ~1080p, so it can't compress a 2304×1296 frame. The real plan: use this full-FoV
> 2304×1296 **sensor** mode, but have the ISP **downscale to 1920×1080** for the
> encoder. Both are 16:9, so full field of view is preserved. Still snapshots
> (JPEG path, no encoder) can use the full 4608×2592.

**2304×1296** remains the right *sensor* mode — full field of view (no bird lost
at the frame edge), fast, ~¼ the data of full-res. For a feeder cam, field of view
beats megapixels. The encoder just receives a 1080p downscale of it.

## Terms worth keeping

- **Photosite** — one light-collecting well on the sensor; measures brightness only.
- **Bayer CFA** — the `R G / G B` color filter array over the photosites.
- **Demosaicing / debayering** — interpolating full RGB from the Bayer mosaic.
- **ISP** — image signal processor (in the VideoCore) — demosaic, white balance,
  exposure, lens correction, etc.
- **MIPI CSI-2** — the high-speed serial camera *data* bus; I²C/CCI is the
  *control* bus.
- **Binning** vs. **cropping** — trade resolution for light/speed vs. trade field
  of view for the same.

## Open threads

- Where exactly does autofocus happen? The IMX708 has a **VCM** (voice-coil motor)
  lens actuator + phase-detect; the ISP/control loop drives it over I²C. (Revisit
  when we tune capture.)
- What does the ISP pipeline output look like once we capture a real JPEG? (Next
  checkpoint.)
