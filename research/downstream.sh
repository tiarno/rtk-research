#!/bin/bash
# Downstream impact of a corrupted base-station position.
#
# Part 1: sweep the 1033 rectype length and show what each value does to
#         sta.pos (uses the harness, i.e. the real decoder).
# Part 2: feed the resulting base-position magnitudes to RTKLIB's own
#         positioning engine and report whether a solution is still produced
#         and what quality flag it carries.
#
#   RTKLIB=/path/to/RTKLIB ./downstream.sh
#
# Part 2 needs rnx2rtkp built from the same checkout:
#   gcc -I src -O2 -o /tmp/rnx2rtkp app/consapp/rnx2rtkp/rnx2rtkp.c \
#       src/*.c src/rcv/*.c -lm -lpthread
set -e

RTKLIB="${RTKLIB:-../rtklib}"
PY="${PY:-python3}"
RNX="${RNX:-/tmp/rnx2rtkp}"
DATA="$RTKLIB/test/data/rinex"

echo "=== Part 1: rectype length -> sta.pos (via the real decoder) ==="
for n in 208 212 215 216 220 223 230 255; do
    "$PY" gen_rtcm.py /tmp/sweep.bin --field rectype --len "$n" >/dev/null
    printf 'n1=%-4s ' "$n"
    ./harness /tmp/sweep.bin 2>&1 | grep 'sta.pos' | tail -1
done

if [ ! -x "$RNX" ] || [ ! -d "$DATA" ]; then
    echo
    echo "skipping part 2: need $RNX and $DATA"
    exit 0
fi

echo
echo "=== Part 2: corrupted base position -> RTK solution ==="
echo "dataset: rover 07590920.05o / base 30400920.05o (base truth from RINEX header)"
echo

cd "$DATA"
run () {  # label x y z
    printf 'ant2-postype=xyz\nant2-pos1=%s\nant2-pos2=%s\nant2-pos3=%s\n' \
        "$2" "$3" "$4" > /tmp/c.conf
    "$RNX" -k /tmp/c.conf -p 2 -o /tmp/c.pos \
        07590920.05o 30400920.05o 07590920.05n >/dev/null 2>&1 || true
    n=$(grep -vc '^%' /tmp/c.pos || true)
    first=$(grep -v '^%' /tmp/c.pos | head -1 | \
            awk '{printf "lat=%s lon=%s h=%s Q=%s", $3,$4,$5,$6}')
    printf '%-24s epochs=%-5s %s\n' "$1" "$n" "${first:-<no solution>}"
}

run "truth"             -3978242.4348 3382841.1715 3649902.7667
run "low 4B (0.44 m)"   -3978242.0000 3382841.1715 3649902.7667
run "low 5B (2.4 m)"    -3978240.0000 3382841.1715 3649902.7667
run "low 6B (46 km)"    -3932160.0000 3382841.1715 3649902.7667
run "pos0=0 (3978 km)"            0.0 3382841.1715 3649902.7667
run "all zero"                    0.0           0.0           0.0
