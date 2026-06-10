# Silicon notes

Low-level learning notes — what's actually happening in the chips, captured as we
hit each one. These grow into the public write-up for andrewpope.io.

One note per topic, added as the build reaches it.

- [01 — How a Raspberry Pi boots (the GPU is in charge)](01-pi-boot-sequence.md) _(Phase 0)_
- [02 — The image sensor: Bayer, two buses, binning vs. cropping](02-image-sensor.md) _(Phase 1)_
- [03 — How a PIR motion sensor actually works](03-how-a-pir-works.md) _(Phase 1)_
- [04 — The hardware H.264 encoder and its 1080p ceiling](04-h264-encoder-ceiling.md) _(Phase 2)_
- [05 — Containers vs. codecs: muxing .h264 into .mp4](05-containers-vs-codecs.md) _(Phase 2/4)_
- [06 — Serving video over HTTP: range requests, 206, and the moov atom](06-http-range-requests.md) _(Phase 5)_
