#!/bin/bash
# Deliver the type 1033 attack over a UART instead of a file or socket.
#
# Proves the attack is transport-independent all the way into RTKLIB's
# real-time server: the bytes arrive on a real tty, which is what a UHF/VHF
# correction radio presents to a rover. No RF is transmitted.
#
#   RTKLIB=/path/to/RTKLIB ./e2e_serial.sh [rectype_len]
#
# No `set -e`: the fortified build is expected to abort, and that is a result.

RTKLIB="${RTKLIB:?set RTKLIB to your RTKLIB checkout}"
PY="${PY:-python3}"
LEN="${1:-212}"
T="${T:-/tmp/rtk-e2e}"
export LIBC_FATAL_STDERR_=1

if [ ! -f "$T/base_attack.rtcm3.tag" ]; then
    echo "run ./e2e.sh first to generate the streams" >&2
    exit 1
fi

gcc -I "$RTKLIB/src" -O2 -U_FORTIFY_SOURCE -o "$T/e2e_plain" \
    e2e_harness.c "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>/dev/null
gcc -I "$RTKLIB/src" -O2 -D_FORTIFY_SOURCE=2 -o "$T/e2e_fortified" \
    e2e_harness.c "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>/dev/null

# RTKLIB prepends /dev/, so reach a pty under /tmp via traversal.
ROVPORT="../tmp/ttyRover:115200:8:n:1:off"
BASPORT="../tmp/ttyBase:115200:8:n:1:off"

run () {  # binary label basestream
    pkill -f serial_feed.py 2>/dev/null
    # The feeder must be killed, not waited on: when the fortified build
    # aborts, nothing drains the pty and the feeder would block forever.
    timeout 30 "$PY" serial_feed.py "$T/rover.rtcm3" "$3" --speed 500 \
        > "$T/feed.log" 2>&1 &
    feeder=$!
    sleep 2
    out=$(timeout 30 "$T/$1" "$ROVPORT" "$BASPORT" 8 500 serial 2>&1) && rc=0 || rc=$?
    { kill $feeder; wait $feeder; } 2>/dev/null
    fb=$(echo "$out" | grep -o 'final base position:.*')
    printf '  %-24s rc=%-4s %s\n' "$2" "$rc" "${fb:-*** aborted, no output ***}"
}

echo "### over a pty (serial transport) ###"
run e2e_plain     "unfortified, clean"  "$T/base.rtcm3"
run e2e_plain     "unfortified, attack" "$T/base_attack.rtcm3"
run e2e_fortified "fortified, attack"   "$T/base_attack.rtcm3"

echo
echo "base station truth:  -3978242.4348 3382841.1715 3649902.7667"
grep -E '^(rover|base) pty|^fed' "$T/feed.log" | tail -3
