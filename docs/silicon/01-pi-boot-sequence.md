# 01 — How a Raspberry Pi boots (the GPU is in charge)

_Phase 0. The Pi Zero 2 W's SoC is the Broadcom BCM2710A1 — four ARM Cortex-A53
cores and a VideoCore IV GPU on one die. The surprising part of boot is who's
driving._

## The one-sentence version

On a Raspberry Pi the **GPU boots first and the ARM CPU is its payload** — the
opposite of a normal PC, where the CPU is in charge from the first instruction.

## What actually happens when you apply power

1. **The ARM cores are held in reset.** All four Cortex-A53 cores start *dead*.
   Nothing runs on the "CPU" yet.
2. **The VideoCore GPU wakes up** and runs a tiny **first-stage bootloader baked
   into on-chip mask ROM** — fixed in the silicon at the factory, unchangeable.
   It knows just enough to talk to the SD card.
3. **It loads `bootcode.bin`** from the SD card's FAT32 boot partition. This is
   the second-stage bootloader — still GPU code, not ARM code.
   _(Pi 4/5 keep this stage in an SPI EEPROM on the board instead. The Zero 2 W
   uses the older flow: it lives on the SD card.)_
4. **`bootcode.bin` reads `config.txt`** and loads **`start.elf`** — effectively
   the GPU's own little firmware/OS.
5. **`start.elf` sets up the system:**
   - splits the 512 MB of RAM between GPU and ARM (the `gpu_mem` knob),
   - loads the **ARM Linux kernel** (`kernel8.img` for 64-bit),
   - loads the **device tree** (`*.dtb`) — a data description of what hardware
     exists and where, so the kernel doesn't have to guess,
   - reads the kernel command line (`cmdline.txt`).
6. **Only now are the ARM cores released from reset** and handed the kernel.
   Linux finally boots on the CPU.

So the GPU is the senior chip at power-on; the ARM is along for the ride. This
isn't trivia — it's *why* the GPU owns the camera ISP and the H.264 encoder we'll
lean on later. The VideoCore was always the boss here.

## Why this makes headless setup possible

That **FAT32 boot partition is just plain files** — readable on any computer,
including a Mac. Raspberry Pi Imager exploits exactly this: after it flashes the
OS image, it reaches back into that partition and drops in your hostname, an SSH
flag, and Wi-Fi credentials. First boot reads those files and configures itself.
No monitor or keyboard required — you're hand-editing the GPU's instructions
before it ever powers on.

## Sidebar: "flashing" vs. "a disk image"

- A **disk image** (`.img`) is a byte-for-byte snapshot of a *whole disk*: the
  partition table, then every partition. Raspberry Pi OS has two — a small
  **FAT32 boot** partition (the files in steps 3–6 above) and a large **ext4
  root** partition (Linux itself).
- **Flashing** is writing those raw bytes to the card block-by-block, *bypassing
  the filesystem* — which is why it wipes the card and why drag-and-drop won't do
  it. The term comes from *flash memory*.

Imager downloads a compressed image (`.img.xz`), decompresses it, writes the raw
bytes, then edits the boot partition to inject your settings.

## Terms worth keeping

- **SoC** — system-on-chip: CPU, GPU, memory controller, peripherals on one die.
- **Mask ROM** — read-only memory patterned directly into the silicon; the
  first-stage bootloader lives here and can never change.
- **Device tree** — a structured description of the hardware passed to the
  kernel, instead of hardcoding it.
- **`gpu_mem`** — the RAM split between GPU and ARM, set in `config.txt`.

## Open threads (to revisit)

- ~~What's the default `gpu_mem` on a 512 MB Lite install, and does the camera
  stack need more?~~ **Resolved (Phase 2):** default is **64 MB** (ARM saw 448 of
  512 MB). The camera/encoder did **not** need more — bumping to 128 MB changed
  nothing. The video failure was the H.264 encoder's macroblock ceiling, not
  memory (see [04](04-h264-encoder-ceiling.md)). `gpu_mem` can revert to 64 to
  give Linux back the RAM for OpenCV.
- Device tree **overlays** — how enabling the camera or a GPIO function edits the
  hardware description at boot. (Phase 1.)
