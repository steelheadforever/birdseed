# 03 — How a PIR motion sensor actually works

_Phase 1. What's happening inside the AM312 when it throws a `MOTION` edge — from
the crystal up to the digital pin._

## "Passive" is the first clue

PIR = **Passive InfraRed**. *Passive* because it emits nothing — it only *listens*
for infrared (heat) radiation already in the scene. (Contrast: ultrasonic/radar
sensors are *active* — they emit a signal and time the echo.) Every warm
body — a bird, your hand — glows in long-wave IR around **9–10 µm**, and that's
what a PIR is tuned to feel.

## The sensing element is a pyroelectric crystal

At the core is a **pyroelectric** material — a crystal that produces a transient
surface charge when its **temperature changes**. Key word: *changes*. IR lands on
it → it warms slightly → it emits a little voltage. Hold the warmth steady and the
signal fades as the crystal re-equilibrates.

**That's why a PIR detects *motion*, not *presence*.** A perfectly still warm
object eventually goes invisible to it. It's a change-detector, not a thermometer.

## The clever bit: two halves in opposition

The element is split into **two halves wired against each other** (differentially).
Here's why that's brilliant:

- The **sun** warming the whole sensor, or ambient temperature drift, hits *both*
  halves equally → the differential cancels it → **no false trigger**.
- A **moving** warm body sweeps across one half, then the other → produces a
  **+then− spike** that does *not* cancel → trigger.

So the design inherently rejects slow, whole-field changes (common-mode) and
responds only to localized lateral motion (differential). It's a hardware noise
filter built from geometry.

## The Fresnel lens chops the view into zones

That faceted white dome isn't decoration — it's a **Fresnel lens array**. It does
two jobs:

1. **Collects** faint IR onto the tiny crystal (the crystal alone sees almost
   nothing).
2. **Divides the field of view into many discrete beams/zones.** As a warm body
   moves laterally, it crosses from zone to zone, alternately lighting up the two
   halves — *manufacturing* the changing differential signal the crystal needs.

A consequence worth knowing for placement: PIRs see **side-to-side motion much
better than motion coming straight at them.** Aim it so birds cross the view.

(The plastic is a special IR-transparent polymer — ordinary glass *blocks* 10 µm
IR, which is why the dome isn't glass.)

## The IC turns microvolts into a clean digital edge

The crystal's output is microvolts of noise-swamped analog. A detection IC:

1. **amplifies** it,
2. runs it through a **window comparator** — fires if the signal swings past a
   threshold in *either* polarity (remember: +then−),
3. **latches the output HIGH** for a fixed time, handling retrigger.

- The bulky **HC-SR501** uses the classic **BISS0001** for this, with trimpots for
  sensitivity and on-time and a retrigger jumper.
- The **AM312** integrates a smaller, lower-power 3.3V IC with **fixed ~2s
  on-time** and auto-retrigger — no pots. That fixed simplicity is exactly why
  it's small, and fine for us.

## Why this shapes birdseed's architecture

The PIR is a near-free "**something warm moved**" wake-up — microamps, no CPU. But
it's **dumb**: it can't tell a bird from a cat, a passing person, or thermal
churn. That's by design, and it's *why* our pipeline is staged:

```
PIR edge (cheap)  →  wake camera  →  OpenCV confirm (Phase 3)  →  save clip
```

Let the µW sensor decide *when to bother looking*; let the camera + CPU decide
*whether it was real*. The dumb sensor protects the power budget; the smart
confirmation protects the storage.

## Terms worth keeping

- **Pyroelectric effect** — temperature *change* in a crystal → transient charge.
- **Common-mode rejection** — the two-halves trick canceling whole-field drift.
- **Fresnel lens** — segmented lens that focuses IR *and* slices the FoV into zones.
- **Long-wave IR (~10 µm)** — body-heat wavelength; needs IR-transparent plastic.
- **Window comparator** — fires on a swing past threshold in either direction.

## Open threads

- How often will sun/thermal effects false-trigger it outdoors? (Measure in the
  field; it's the load the Phase 3 confirmation pass has to carry.)
- Optimal mounting height/angle relative to the perch for lateral crossings.
