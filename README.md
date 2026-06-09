# birdseed

A cloudless bird feeder camera. Fully self-hosted, no subscription, no cloud
hosting cost — a Raspberry Pi acts as its own server on the home network. Built
as a public learning artifact in embedded systems and trusted, self-contained
hardware: a device that detects, captures, and serves on the metal it runs on.

The design principle everything else follows from: **keep the Pi dumb.** The
device only detects motion and saves clips. Any classification (bird ID) happens
later, client-side on the phone. A dumb device is a power-efficient device, and
the power budget is the hard constraint of an off-grid, solar-fed feeder cam.

> This repo is a learning project as much as a build. Silicon-level explanations
> are first-class artifacts, not footnotes — see [`docs/silicon/`](docs/silicon/).
> We move one small, provable slice at a time. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Hardware (confirmed on hand)

| Part | What it is | Notes |
|------|-----------|-------|
| Compute | **Pi Zero 2 W** (with header) | BCM2710A1 — quad Cortex-A53, ARMv8, runs 64-bit RPi OS |
| Camera | **Camera Module 3**, autofocus | Sony IMX708, 12 MP; autofocus because birds don't pose at a fixed distance |
| Motion | **HC-SR501** PIR | VCC from **5 V**; OUT is **3.3 V** logic → straight to a GPIO, no level shifter. Retrigger jumper → **H** |
| CSI cable | Pi Zero narrow CSI adapter | The wide cable in the Cam Module 3 box does NOT fit the Zero's port — this one does |
| Wiring | Female-to-female jumpers | For the PIR |
| Storage | microSD (high-endurance recommended) | Clip writes hammer the card |

### Power chain (later phase, not yet on hand)

`10 W solar panel → charge controller → LiFePO4 battery`

LiFePO4, not 18650 Li-ion: handles outdoor temperature swings and lasts 5–10
years vs. 1–2. Sized for **3–5 cloudy days** of autonomy. During dev the Pi just
runs off USB power.

### Enclosure (later phase)

IP66 (Hammond 1554-style) with a clear acrylic window. Camera in a **separate**
housing mounted ~12–18" from the perch — not built into the feeder.

## Software architecture

```
   PIR (hardware trigger)  ─┐
                            ├─► capture (picamera2) ─► OpenCV bg-subtraction
                            │      confirmation pass (reject false triggers)
                            │              │
                            │              ▼
                            │      ring-buffer storage
                            │      (H.264 MP4 clips, delete oldest over size cap)
                            │              │
                            └──────────────┴─► FastAPI ──► REST API + live MJPEG
                                                              │
   PWA (installable on iOS) ◄── Tailscale (remote) ◄──────────┘
   ntfy.sh push notifications ◄──────────────────────────────┘

   Bird ID (phase 2): client-side on the phone (Core ML), never on the Pi.
```

- **OS / runtime:** Raspberry Pi OS Lite (64-bit) + Python
- **Capture:** `picamera2`; PIR as the hardware trigger
- **Confirmation:** OpenCV background-subtraction pass to reject false PIR triggers
- **Storage:** local ring buffer — H.264 MP4 clips, oldest deleted over a size cap
- **Serving:** FastAPI on the Pi — REST API + live MJPEG preview
- **Frontend:** PWA, installable on iOS
- **Remote access:** Tailscale
- **Notifications:** ntfy.sh
- **Bird ID:** deferred to phase 2, runs client-side on the phone (Core ML)

### Where the work happens on the chip

Worth holding in your head, because it's why a tiny Pi can do this at all:

- **Camera ISP + H.264 clip encoding** → the **VideoCore IV GPU** block in the SoC,
  not the ARM cores. Recording clips barely touches the CPU.
- **OpenCV confirmation pass + FastAPI/Python** → the **ARM Cortex-A53 cores**.
  Cheap by design — the "dumb Pi" rule keeps CPU work minimal.

### Hardware abstraction (build before / alongside the Pi)

A thin interface separates app logic from Pi-specific hardware, with two
implementations behind it:

- **Mock** (`MockCamera`, `MockMotionSensor`) — runs on the dev Mac, feeds test
  video and synthetic triggers. The full pipeline can be built and tested with no
  Pi attached.
- **Real** (`Picamera2Camera`, `GpioPirSensor`) — the actual drivers, selected on
  the Pi via config, no app-logic changes.

## Repo layout

```
birdseed/
├── README.md          ← this file (source of truth for the design)
├── docs/
│   ├── ROADMAP.md      ← phased build plan
│   └── silicon/        ← low-level learning notes (grow into the public write-up)
├── pi/                 ← on-device software (capture, confirm, store, serve)
└── web/                ← PWA frontend
```
