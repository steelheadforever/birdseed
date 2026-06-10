# 07 — Flash wear, write amplification, and why a ring buffer is kind to the card

_Phase 4. The clips dir is now a byte-capped ring buffer (delete oldest over a cap).
This note is about the thing the cap really protects: the SD card's finite ability
to be written, and why our access pattern is close to the gentlest one flash allows._

## The failure mode isn't "full," it's "worn out"

An SD card is **NAND flash**. Its cells don't last forever: each one tolerates a
limited number of **program/erase (P/E) cycles** before it stops reliably holding
charge. Rough orders of magnitude by cell type:

| NAND type | bits/cell | ~P/E cycles | where you find it |
|-----------|-----------|-------------|-------------------|
| SLC | 1 | ~50k–100k | industrial |
| MLC | 2 | ~3k | good "high-endurance" cards |
| TLC | 3 | ~500–1k | cheap consumer cards |

A bird feeder that records all day is a *continuous write workload*. So the
long-term enemy isn't running out of space (the ring buffer fixes that on day
one) — it's **wearing the card out**, months in, when some block has been
erased one too many times. Everything below is about slowing that down.

## Why you can't just "overwrite" — and how that multiplies writes

Flash has an awkward asymmetry baked into the silicon:

- It's **written in pages** (say 4–16 KB) but
- **erased only in much larger blocks** (say 128 KB–4 MB), and
- a page **cannot be rewritten in place** — its block must be erased first.

So to change even one byte, the controller reads the surrounding live data,
writes it somewhere new, and erases the old block. The result: **one logical write
causes several physical writes**. That ratio is **write amplification (WA)**, and
WA > 1 means the card wears faster than your data volume alone suggests. Tiny
random writes and constant filesystem-metadata churn (FAT tables, journals) are
the worst offenders.

A chip you never see manages all this: the **Flash Translation Layer (FTL)** in
the card's controller. It remaps logical sectors to physical blocks and does
**wear leveling** — spreading erases so no single block dies early. Cheap cards
have a weak FTL; this is a big part of what you're actually buying with a
"high-endurance" card (better NAND *and* a smarter controller with more spare
area).

## Why birdseed's pattern is near the gentle end

Three things about how we write and prune line up well with what flash wants:

1. **Big sequential writes.** A clip is one ~10 MB contiguous file written start to
   finish. Large sequential writes align with erase blocks and barely touch
   metadata — the *opposite* of the random-small-write pattern that drives WA up.
   (The "dumb Pi" rule helps here too: we only write on a real motion event, not
   continuously.)

2. **Delete-oldest keeps free space high — and free space is what wear leveling
   runs on.** A nearly-full card gives the FTL almost no room to relocate data, so
   WA climbs and the same few free blocks get hammered. By capping the ring buffer
   *below* the card's size, we leave a permanent pool of free blocks for the
   controller to rotate through. **The headroom is the point** — the cap should sit
   well under the card capacity, not just under "full." (This build's 32 GB card
   with a ~16 GB clip cap stays roughly half-empty even after the OS — a large
   permanent free pool for the FTL to rotate through.)

3. **Whole-file deletes, not in-place edits.** Evicting a clip frees a large
   contiguous region the FTL can reclaim and pre-erase, rather than churning a file
   in place. Deletion is the cheap direction.

There's one catch: a filesystem delete only marks space free in *its* tables — the
card's controller may not know those blocks are reusable until told. **TRIM**
(`fstrim` on Linux/ext4) is that message: "these blocks are dead, you may pre-erase
them." Running it periodically lets the FTL stay ahead, lowering WA. Worth enabling
on the Pi — tracked below.

## How the code embodies this

`storage.enforce_size_cap()` sorts our `clip_*.mp4` files oldest-first (by the
capture timestamp in the name — note 06), sums their sizes, and `unlink()`s from
the oldest end until the total is under the cap, never deleting the single newest.
The recorder calls it right after each save; `run.py` sets the cap (default 2 GB,
`BIRDSEED_CLIP_CAP_MB`). The *writer* prunes — the read-only server never does.

## Terms worth keeping

- **NAND flash / P/E cycle** — the storage medium; its per-cell erase budget.
- **Page vs. block** — write granularity vs. erase granularity; the asymmetry behind WA.
- **Write amplification (WA)** — physical writes ÷ logical writes; > 1 wears the card faster.
- **FTL / wear leveling** — the controller logic that remaps and spreads erases.
- **Spare area / over-provisioning** — hidden free blocks the FTL rotates through.
- **TBW** — terabytes-written endurance rating; the card's lifetime write budget.
- **TRIM / `fstrim`** — telling the card which blocks are free so it can pre-erase.
- **Ring buffer** — bounded newest-in/oldest-out store; what the clips dir now is.

## Open threads

- Enable periodic **`fstrim`** on the Pi (or `discard` mount option) so deletes actually reach the FTL.
- Size the cap against the card's **TBW** and our clip rate to estimate years-to-wear-out — a back-of-envelope worth doing once we know real capture volume outdoors.
- Consider a **separate partition** for clips so OS/system writes and clip writes don't share wear.
- Fragmented MP4 (notes 05/06) for power-loss resilience pairs naturally with this phase.
