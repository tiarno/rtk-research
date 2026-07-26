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
# latency: square wave in, measure the lag out.
# speed:   constant ramp in, check the ground speed the RMC reports. RTKLIB's
#          own writer says 0.00 knots at any speed; the harness derives it.
MODE="${MODE:-latency}"
RAMP="${RAMP:-1.0}"
RAMPDIR="${RAMPDIR:-0}"   # bearing, degrees; 0=north, 90=east
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
# See loop_demo.sh: a failed build must not leave the previous binary running.
# -DSVR_REUSEADDR: RTKLIB only sets SO_REUSEADDR on a TCP server when built
# with this, so without it every run leaves :5901/:5902/:5903 unbindable for
# the TIME_WAIT window and the next run dies at startup. A demo you cannot
# immediately retry is not a demo.
rm -f "$T/gnss_sim" "$T/e2e_loop"
gcc -I "$RTKLIB/src" -O2 -DSVR_REUSEADDR -o "$T/gnss_sim" "$HERE/gnss_sim.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread || {
        echo "build failed: gnss_sim.c"; exit 1; }
gcc -I "$RTKLIB/src" -O2 -DSVR_REUSEADDR -U_FORTIFY_SOURCE -o "$T/e2e_loop" "$HERE/e2e_harness.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread || {
        echo "build failed: e2e_harness.c"; exit 1; }
[ -x "$T/gnss_sim" ] && [ -x "$T/e2e_loop" ] || { echo "build failed"; exit 1; }

BASE_ECEF=-3978242.4348,3382841.1715,3649902.7667
cd "$T" || exit 1

echo "### feeder -> gnss_sim (:5901 base, :5902 rover) ###"
[ "$MODE" = speed ] && FEEDOPT="--ramp $RAMP --ramp-dir $RAMPDIR" || FEEDOPT=""
python3 "$HERE/loop_latency.py" feed --seconds "$((SECS + 20))" $FEEDOPT \
        --events "$T/lat_fed.csv" 2>"$T/lat_feed.log" \
  | "$T/gnss_sim" "$RTKLIB/test/data/rinex/07590920.05n" "$BASE_ECEF" \
        --live :5901 :5902 5 > "$T/lat_sim.log" 2>&1 &
sleep 8

echo "### relay :5911 -> :5901 (no injection) ###"
python3 "$HERE/inject_relay.py" --listen 5911 --upstream 127.0.0.1:5901 \
        --len 0 > "$T/lat_relay.log" 2>&1 &
sleep 3

echo "### RTKLIB, NMEA out :5903 ###"
# The speed check is a check ON the harness's own NMEA, so it must be the
# harness writing it. The latency run leaves RTKLIB's writer in place, since
# what it times is the pipeline, not the sentence contents.
[ "$MODE" = speed ] && export NMEA_VEL=1
NMEA_TCP=:5903 "$T/e2e_loop" 127.0.0.1:5902 127.0.0.1:5911 "$((SECS + 10))" 1 tcp \
        > "$T/lat_rtklib.log" 2>&1 &
sleep 6

if [ "$MODE" = speed ]; then
    echo "### reading RMC for ${SECS}s (fed ${RAMP} m/s on bearing ${RAMPDIR}) ###"
    python3 "$HERE/loop_latency.py" speed --seconds "$SECS" --expect "$RAMP" \
            --expect-course "$RAMPDIR"
    rc=$?
    cleanup
    wait 2>/dev/null
    exit $rc
fi

echo "### reading NMEA for ${SECS}s ###"
python3 "$HERE/loop_latency.py" read --seconds "$SECS" \
        --samples "$T/lat_got.csv" 2>&1 | tail -2

cleanup
wait 2>/dev/null

echo
python3 "$HERE/loop_latency.py" analyse \
        --events "$T/lat_fed.csv" --samples "$T/lat_got.csv"
