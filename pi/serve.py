#!/usr/bin/env python3
"""Entry point for the serving layer — a read-only HTTP view over the clips dir.

    python3 pi/serve.py            # listens on 0.0.0.0:8000

This is wholly separate from the capture loop (run.py): a different process, no
shared state but the clips directory on disk. See birdseed/server.py for why.

We bind 0.0.0.0 (every interface) rather than 127.0.0.1 (loopback only) on
purpose: the whole point is that another device on the LAN — your phone — can
reach the Pi at http://birdseed.local:8000. `birdseed.local` resolves via mDNS
(Bonjour/Avahi), so there's no router config or IP to memorize.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the birdseed package importable no matter where this is run from.
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn  # noqa: E402  (after the sys.path tweak, by design)

from birdseed.server import app  # noqa: E402


def main() -> None:
    port = int(os.environ.get("BIRDSEED_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
