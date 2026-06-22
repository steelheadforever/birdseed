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

# ---- self-heal hardening: an unattended outdoor feeder must come back on its
# own after a power bump. Three independent layers (see each file's comment):
#   - Wi-Fi power-save off, so the radio re-associates after a network blip
#   - a network-check timer that bounces Wi-Fi, then reboots if truly wedged
#   - the SoC hardware watchdog, to reboot on a total kernel/systemd hang
echo
echo "installing self-heal hardening..."

# 1. Wi-Fi power-save off (NetworkManager drop-in). Restart NM to apply now.
sudo cp "$HERE"/wifi-powersave-off.conf /etc/NetworkManager/conf.d/
sudo systemctl restart NetworkManager

# 2. Network self-heal timer. The script runs in place from the repo, so just
#    make sure it's executable; the unit references it by absolute path.
chmod +x "$HERE"/birdseed-netcheck.sh
sudo cp "$HERE"/birdseed-netcheck.service \
        "$HERE"/birdseed-netcheck.timer \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now birdseed-netcheck.timer

# 3. Hardware watchdog (systemd drop-in). daemon-reexec re-reads system.conf so
#    the watchdog arms now, without a reboot. Warn if the device is missing.
sudo mkdir -p /etc/systemd/system.conf.d
sudo cp "$HERE"/watchdog.conf /etc/systemd/system.conf.d/
sudo systemctl daemon-reexec
if [ -e /dev/watchdog ]; then
  echo "  hardware watchdog armed (/dev/watchdog present)."
else
  echo "  WARNING: /dev/watchdog not found — watchdog config copied but inactive."
  echo "           On most Pi OS builds it's enabled by default; if not, add"
  echo "           'dtparam=watchdog=on' to /boot/firmware/config.txt and reboot."
fi

# ---- settings tab: let the web UI reboot / restart services without SSH.
# Grant the server NOPASSWD sudo on exactly those two commands (and nothing
# else). visudo -c validates the file BEFORE we install it — a malformed
# sudoers can lock you out of sudo, so we never copy an unchecked one.
echo
echo "installing remote-control sudoers rule..."
if sudo visudo -c -f "$HERE"/birdseed-sudoers >/dev/null; then
  sudo install -m 0440 -o root -g root "$HERE"/birdseed-sudoers /etc/sudoers.d/birdseed
  echo "  sudoers rule installed (reboot + restart birdseed.target)."
else
  echo "  WARNING: birdseed-sudoers failed validation; NOT installed."
  echo "           The web reboot/restart buttons will be inoperative until fixed."
fi

echo
echo "birdseed is up, and will start on every boot from cold."
echo
echo "  watch it run:   journalctl -u birdseed-recorder -u birdseed-server -f"
echo "  status:         systemctl status birdseed-recorder birdseed-server"
echo "  stop/start both: sudo systemctl stop|start|restart birdseed.target"
echo "  net self-heal:  systemctl status birdseed-netcheck.timer; journalctl -t birdseed-netcheck"
echo "  watchdog:       systemctl show -p RuntimeWatchdogUSec  # nonzero = armed"
echo "  the site:       http://birdseed.local:8000"
