#!/bin/bash
# Task 2: what does the aircraft do with a quietly-corrupted RTK position?
#
# Starts ArduPilot SITL configured to take its position from an external
# source (GPS_TYPE=14, MAV) -- the companion-computer-running-RTKLIB
# deployment -- then feeds it the position offset measured in the rest of
# this repo, with the fix flag pinned at RTK FIXED throughout.
#
# Easiest way to get a SITL binary is the official prebuilt one -- no toolchain
# needed, and it is a stock build rather than a locally patched one:
#
#   mkdir -p ~/apsitl && cd ~/apsitl
#   curl -LO https://firmware.ardupilot.org/Copter/stable/SITL_x86_64_linux_gnu/arducopter
#   chmod +x arducopter
#
#   BIN=~/apsitl/arducopter ./sitl_demo.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"   # resolve before we cd into $T
BIN="${BIN:-$HOME/apsitl/arducopter}"
T="${T:-/tmp/rtk-sitl}"
mkdir -p "$T"

if [ ! -x "$BIN" ]; then
    echo "no SITL binary at $BIN -- see the header of this script" >&2
    exit 1
fi

cat > "$T/defaults.parm" <<'EOF'
ARMING_CHECK 0
FRAME_CLASS 1
LOG_DISARMED 1
SR0_POSITION 10
SR0_EXTRA1 10
SR0_EXTRA3 10
SR0_EXT_STAT 10
EOF

# -x matches the process NAME exactly. Do not use `pkill -f arducopter`: that
# matches any command line containing the string, including the shell that
# invoked this script with BIN=.../arducopter, which kills our own parent.
pkill -x arducopter 2>/dev/null
sleep 1

# A bare EEPROM has no INS calibration, and ArduPilot refuses to arm with
# "3D Accel calibration needed" regardless of ARMING_CHECK. ArduPilot's own
# SITL defaults supply it, so chain them ahead of ours when available.
# (Only needs the source tree for this one file:
#  git clone --depth 1 https://github.com/ArduPilot/ardupilot)
AP_DEFAULTS="${AP_DEFAULTS:-$HOME/ardupilot/Tools/autotest/default_params/copter.parm}"
if [ -f "$AP_DEFAULTS" ]; then
    DEFAULTS="$AP_DEFAULTS,$T/defaults.parm"
else
    echo "warning: $AP_DEFAULTS not found; arming may fail on INS calibration" >&2
    DEFAULTS="$T/defaults.parm"
fi

cd "$T" || exit 1
"$BIN" --model quad --home 35.160876298,139.613834769,70.2814,0 \
       --defaults "$DEFAULTS" --serial0 tcp:5760 \
       > "$T/sitl.log" 2>&1 &
sitl=$!
echo "SITL pid $sitl, waiting for it to come up..."
sleep 12

python3 "$HERE/ardupilot_demo.py" --conn tcp:127.0.0.1:5760 "$@"
rc=$?

# Give the log a moment to flush, then analyse the newest one.
sleep 3
kill $sitl 2>/dev/null
wait $sitl 2>/dev/null
LOG=$(ls -t "$T"/logs/*.BIN 2>/dev/null | head -1)
if [ -n "$LOG" ]; then
    echo
    echo "=== analysing $LOG ==="
    python3 "$HERE/parse_sitl_log.py" "$LOG"
fi
exit $rc
