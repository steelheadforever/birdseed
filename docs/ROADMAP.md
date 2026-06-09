# Roadmap

One small, provable slice at a time. Each phase ends with something that
demonstrably works, and each leaves behind a silicon note in `docs/silicon/`
where it touched real hardware. We don't start a phase until the previous one is
solid.

| Phase | Goal — "done" means… | Silicon we'll learn |
|-------|----------------------|---------------------|
| **0. Foundation** | Repo scaffolded; Pi imaged and booting headless; we can SSH in. | Pi boot sequence (VideoCore ROM → bootloader → kernel), `config.txt`, the CPU/GPU memory split |
| **1. Prove the sensors** | Capture one photo from the Cam Module 3; read a real PIR trigger on a GPIO. | MIPI CSI-2 lanes, the IMX708 sensor + ISP pipeline, GPIO input / pull resistors, the BISS0001 + pyroelectric element |
| **2. Capture pipeline** | PIR fires → record an H.264 clip. Hardware-abstraction layer + mocks so it also runs on the Mac. | VideoCore hardware H.264 encoder; why encoding offloads the CPU |
| **3. Confirmation pass** | OpenCV background subtraction rejects false PIR triggers before saving. | Frame differencing on the ARM cores; cost of CPU vision vs. the encoder block |
| **4. Storage** | Ring buffer: clips written, oldest deleted over a size cap. | Flash wear, why high-endurance SD, write amplification |
| **5. Serving** | FastAPI on the Pi: REST API + live MJPEG preview in a browser. | MJPEG vs. H.264 tradeoffs, serving from a constrained device |
| **6. Frontend** | PWA, installable on iOS, talking to the Pi's API. | (mostly software) |
| **7. Remote + notify** | Tailscale remote access; ntfy.sh push on a confirmed event. | NAT traversal / WireGuard basics |
| **8. Power** | Solar → charge controller → LiFePO4; measured power budget, 3–5 day autonomy. | Battery chemistry, charge control (MPPT vs PWM), the Pi's PMIC & 5 V rail |
| **9. Bird ID (later)** | Client-side Core ML classification on the phone. | On-device inference, the Apple Neural Engine |

**Phases 0–2 complete** (Pi boots headless · camera + PIR proven · birdseed's own
loop records H.264 clips on a real motion trigger). **Current phase: 3 —
Confirmation pass.**
