#!/usr/bin/env bash
# birdseed-netcheck — keep the unattended feeder on the network.
#
# After a power bump or router reboot the Pi Zero 2 W sometimes stays powered
# but never rejoins Wi-Fi (the failure we hit). A hardware watchdog can't fix
# that — the kernel is alive and happily petting it; it's just offline. So this
# runs on a timer and escalates gently:
#
#   1. reachable            -> clear the counter, done.
#   2. unreachable          -> bounce NetworkManager to force re-association.
#   3. unreachable for ~10m -> reboot (last resort; clears a wedged radio).
#
# The failure counter lives in /run (tmpfs), so it resets to zero on every
# boot — a reboot is always a clean slate, never a loop primed from last time.
#
# Deliberately conservative about rebooting: it takes REBOOT_AFTER *consecutive*
# failed checks, so a single dropped packet or a router that's slow to come back
# from the same outage won't cycle the Pi. Restarting NetworkManager, by
# contrast, is cheap and happens on every failed check.
set -uo pipefail

STATE=/run/birdseed-netcheck.fails
REBOOT_AFTER=5   # consecutive failures before reboot (timer fires every 2 min)

# Ping the default gateway — the thing we actually need to reach to serve the
# LAN. Fall back to a public IP only if there's no default route at all.
gateway="$(ip route 2>/dev/null | awk '/default/ {print $3; exit}')"
target="${gateway:-1.1.1.1}"

if ping -c2 -W2 "$target" >/dev/null 2>&1; then
  rm -f "$STATE"
  exit 0
fi

fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"
logger -t birdseed-netcheck "unreachable ($target), failure #${fails}; restarting NetworkManager"
systemctl restart NetworkManager

if [ "$fails" -ge "$REBOOT_AFTER" ]; then
  logger -t birdseed-netcheck "still offline after ${fails} checks; rebooting"
  rm -f "$STATE"
  systemctl reboot
fi
