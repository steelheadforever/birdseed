#!/usr/bin/env bash
#
# One-time setup. Run this ONCE on the Pi. After it, birdseed starts on every
# cold boot with zero commands, and restarts itself if either half crashes:
#
#   bash ~/birdseed/pi/systemd/install.sh
#
# Re-run it any time you edit the unit files (it just re-copies and reloads).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

# Drop the units where systemd looks for them, reload, enable (= autostart on
# boot) and start now.
sudo cp "$HERE"/birdseed-recorder.service \
        "$HERE"/birdseed-server.service \
        "$HERE"/birdseed.target \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now birdseed-recorder.service birdseed-server.service

echo
echo "birdseed is up, and will start on every boot from cold."
echo
echo "  watch it run:   journalctl -u birdseed-recorder -u birdseed-server -f"
echo "  status:         systemctl status birdseed-recorder birdseed-server"
echo "  stop/start both: sudo systemctl stop|start|restart birdseed.target"
echo "  the site:       http://birdseed.local:8000"
