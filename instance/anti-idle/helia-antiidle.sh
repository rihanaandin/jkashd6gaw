#!/bin/bash
# helia-antiidle — keeps an OCI Always Free instance above Oracle's idle-reclaim
# threshold (CPU p95 < 20% over 7 days => idle => reclaimed).
#
# Method: duty-cycled single-thread busy loop.
#   WORK  seconds busy  (sha256sum /dev/zero = steady single-core userspace load)
#   SLEEP seconds rest
# Default 40/20 = ~67% duty — comfortably above the 20% threshold with margin,
# without burning burst credits as fast as a 100% loop.
#
# Tuning: override WORK/SLEEP via systemd Environment= lines.
# Removal: sudo systemctl disable --now helia-antiidle
#          sudo rm /etc/systemd/system/helia-antiidle.service /usr/local/bin/helia-antiidle.sh
#          sudo systemctl daemon-reload

WORK=${WORK:-40}
SLEEP=${SLEEP:-20}

echo "[helia-antiidle] started: ${WORK}s busy / ${SLEEP}s rest (duty $(( WORK * 100 / (WORK + SLEEP) ))%)"

while true; do
    # busy phase: hash an endless zero stream (pure CPU, no disk/network wear)
    timeout "${WORK}" sha256sum /dev/zero >/dev/null 2>&1
    # rest phase
    sleep "${SLEEP}"
done
