#!/bin/bash
# Measure the loop delay with no vehicle in it.
#
#   feeder --> gnss_sim --> relay --> RTKLIB --> NMEA --> timestamping reader
#
# Same chain loop_demo.sh builds, minus SITL, so a square wave in latitude goes
# in and the lag to the far end is measurable without anything able to
# destabilise. See loop_latency.py.
#
#   RTKLIB=<checkout> ./loop_latency.sh [seconds]
#
# The relay is included with injection disabled: it is part of the path the
# aircraft's position travels, so its buffering counts toward the delay.

RTKLIB="${RTKLIB:?set RTKLIB to your RTKLIB checkout}"
SECS="${1:-90}"
HERE="$(cd "$(dirname "$0")" && pwd)"
T="${T:-/tmp/rtk-loop}"
mkdir -p "$T"

cleanup() {
    for p in gnss_sim e2e_loop; do pkill -x $p 2>/dev/null; done
    pkill -f 'loop_latency.py feed' 2>/dev/null
    pkill -f 'inject_relay.py --listen' 2>/dev/null
}
cleanup; sleep 1

echo "### building ###"
gcc -I "$RTKLIB/src" -O2 -o "$T/gnss_sim" "$HERE/gnss_sim.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>&1 | grep -Ei '\berror\b'
gcc -I "$RTKLIB/src" -O2 -U_FORTIFY_SOURCE -o "$T/e2e_loop" "$HERE/e2e_harness.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>&1 | grep -Ei '\berror\b'
[ -x "$T/gnss_sim" ] && [ -x "$T/e2e_loop" ] || { echo "build failed"; exit 1; }

BASE_ECEF=-3978242.4348,3382841.1715,3649902.7667
cd "$T" || exit 1

echo "### feeder -> gnss_sim (:5901 base, :5902 rover) ###"
python3 "$HERE/loop_latency.py" feed --seconds "$((SECS + 20))" \
        --events "$T/lat_fed.csv" 2>"$T/lat_feed.log" \
  | "$T/gnss_sim" "$RTKLIB/test/data/rinex/07590920.05n" "$BASE_ECEF" \
        --live :5901 :5902 5 > "$T/lat_sim.log" 2>&1 &
sleep 8

echo "### relay :5911 -> :5901 (no injection) ###"
python3 "$HERE/inject_relay.py" --listen 5911 --upstream 127.0.0.1:5901 \
        --len 0 > "$T/lat_relay.log" 2>&1 &
sleep 3

echo "### RTKLIB, NMEA out :5903 ###"
NMEA_TCP=:5903 "$T/e2e_loop" 127.0.0.1:5902 127.0.0.1:5911 "$((SECS + 10))" 1 tcp \
        > "$T/lat_rtklib.log" 2>&1 &
sleep 6

echo "### reading NMEA for ${SECS}s ###"
python3 "$HERE/loop_latency.py" read --seconds "$SECS" \
        --samples "$T/lat_got.csv" 2>&1 | tail -2

cleanup
wait 2>/dev/null

echo
python3 "$HERE/loop_latency.py" analyse \
        --events "$T/lat_fed.csv" --samples "$T/lat_got.csv"
