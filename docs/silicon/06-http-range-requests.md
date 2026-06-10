# 06 — Serving video over HTTP: range requests, 206, and where the `moov` atom has to live

_Phase 5. How a browser plays and scrubs a clip it hasn't fully downloaded, why
that costs the Pi almost nothing, and why it's a callback to note 05's `moov`
atom._

## The problem: don't download the whole clip to watch the start of it

A `<video src="/clips/x.mp4">` pointed at a 40 MB clip should start playing
almost immediately, and you should be able to drag the scrubber to the 6-second
mark without first pulling all 40 MB. Plain "GET the file" can't do that — it's
all-or-nothing, front to back. The fix is a feature built into HTTP itself:
**byte-range requests**.

## The 206 dance

The server advertises the capability on a normal response:

```
GET /clips/x.mp4
200 OK
Accept-Ranges: bytes        ← "you may ask me for byte ranges"
Content-Length: 233036
```

The browser then asks for just the bytes it wants:

```
GET /clips/x.mp4
Range: bytes=0-1023         ← "only the first 1 KB, please"
206 Partial Content         ← NOT 200 — a different status code
Content-Range: bytes 0-1023/233036
Content-Length: 1024        ← length of *this slice*, not the file
```

`206 Partial Content` is the whole game: random access to a file over HTTP, one
byte range at a time. To scrub, the player just issues a new `Range:` request for
the bytes covering the new timestamp. We proved this against the live server —
`Range: bytes=0-1023` came back `206` with `Content-Range: bytes 0-1023/233036`.

We get it **for free** from Starlette's `FileResponse`: it reads the `Range`
header, seeks to that offset in the file, and returns the slice with the right
status and headers. We wrote zero range-handling code (only the path-traversal
guard, so a clip name can't escape the clips directory).

## How the player knows *which* bytes to ask for — the `moov` atom (callback to 05)

Range requests are byte-addressed, but you scrub in *seconds*. What translates "go
to t=6s" into "fetch bytes 1.2M–1.5M"? The MP4's **`moov` atom** — the seek index
from note 05. The player reads `moov`, looks up which byte range holds the frames
near t=6s, and issues a `Range:` request for exactly those bytes.

So `moov` placement suddenly matters for *streaming*, not just for playability:

- **`moov` at the end** (ffmpeg's default): to learn the file's layout, the player
  must first read the end of the file. Over range-capable HTTP it can do that with
  an extra round trip — annoying but survivable.
- **`moov` at the front** (`-movflags +faststart`): the player learns the layout
  from the first bytes and can start playing/seeking immediately. This is why the
  test clips for this phase were muxed with `+faststart`.

The open thread from note 05 now has teeth: birdseed's real `FfmpegOutput` writes
`moov` on clean stop, but likely at the **end**. For snappy phone playback we
probably want `+faststart` (or fragmented MP4) on the recorder's output too.
Tracked below.

## Why this is nearly free for the Pi (the "dumb server" point)

Serving a clip touches **no video machinery**. The VideoCore encoded the H.264
*once*, at capture (note 04). Serving is then pure file I/O — the ARM cores read
byte ranges off the SD card and hand them to the network stack. No decode, no
re-encode, no transcode. That's why a Pi Zero 2 W can serve clips to several
phones at once without breaking a sweat: it isn't doing video work, it's being a
file server. It also keeps faith with the project's spine — the device stays dumb;
the *browser* decodes and renders.

Contrast the thing we deliberately did **not** build this phase: a live MJPEG
preview. That one *isn't* free — it keeps the camera + ISP powered and pushes a
fat, uncompressed-between-frames stream over the wifi radio continuously. Serving
recorded clips is event-shaped and cheap; live streaming is always-on and a power
sink. (Deferred to a gated "setup mode" — its own note when we build it.)

## Reaching the Pi at all: `0.0.0.0` + mDNS

`serve.py` binds `0.0.0.0` (all interfaces), not `127.0.0.1` (loopback only), so a
*different* device on the LAN can connect. Your phone finds the Pi at
`http://birdseed.local:8000` because Raspberry Pi OS runs **Avahi** (mDNS /
Bonjour): the `.local` name resolves by multicast on the local network — no router
config, no static IP to memorize. No cloud anywhere in that path, which is the
entire thesis.

## Terms worth keeping

- **Range request** — `Range: bytes=a-b`; asks for part of a resource.
- **206 Partial Content** — the success status for a served range (vs. 200).
- **Accept-Ranges / Content-Range** — headers advertising the capability / describing the returned slice.
- **`moov` atom** — MP4 seek index (note 05); maps timestamps → byte offsets, so it drives which ranges the player fetches.
- **`+faststart`** — muxer flag putting `moov` at the file's front for instant streaming/seeking.
- **mDNS / Avahi / Bonjour** — multicast name resolution; what makes `birdseed.local` work with no DNS server.

## Open threads

- Add `+faststart` (or fragmented MP4) to the recorder's `FfmpegOutput` so real clips seek instantly on a phone — folds in with the crash-resilience thread from note 05.
- The storage cap (pruning oldest clips) is the *writer's* job — lands in the recorder next, not the server.
- Live preview as a gated, auto-timeout "setup mode" — the MJPEG-vs-radio power note gets written then.
