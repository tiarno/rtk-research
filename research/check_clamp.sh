#!/bin/bash
# Does the proposed decode_type1033 clamp fix the defect without changing
# anything else?
#
#   RTKLIB=<checkout> ./check_clamp.sh
#
# Builds the harness twice -- once against the stock checkout, once against a
# tree where the only difference is the clamp -- and runs the same streams
# through both. Also runs each under UBSan, because that is how FuzzingLabs
# reproduced the bug and the control has to fire before "clean" means anything.
#
# The clamp is five lines placed after the frame-length check (which must keep
# using the declared lengths -- it is the wire framing test) and after the read
# loops (which already cap at 31), immediately before the strncpy block:
#
#     if (n >31) n =31;  ... if (n3>31) n3=31;
#
# Nothing is written to the RTKLIB checkout: the patched tree is symlinks to it
# with a single real, modified copy of rtcm3.c.
set -e

RTKLIB="${RTKLIB:?set RTKLIB to your RTKLIB checkout}"
SRC="$RTKLIB/src"
HERE="$(cd "$(dirname "$0")" && pwd)"
T="${T:-/tmp/rtk-clamp}"

[ -f "$SRC/rtklib.h" ] || { echo "no rtklib.h under $SRC" >&2; exit 1; }

mkdir -p "$T/patched/src"
rm -f "$T/patched/src"/*

for f in "$SRC"/*; do
    [ -f "$f" ] && ln -sf "$f" "$T/patched/src/$(basename "$f")"
done

# Insert the clamp into decode_type1033 only. The anchor also appears in
# decode_type1007/1008, so the edit is scoped to the function first.
rm -f "$T/patched/src/rtcm3.c"
python3 - "$SRC/rtcm3.c" "$T/patched/src/rtcm3.c" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
anchor = '    sprintf(rtcm->sta.name,"%04d",staid);\n'
clamp = """    /* clamp descriptor lengths to the staging buffers' capacity */
    if (n >31) n =31;
    if (m >31) m =31;
    if (n1>31) n1=31;
    if (n2>31) n2=31;
    if (n3>31) n3=31;
"""
a = text.index("static int decode_type1033(")
b = text.index("\n}", a)
body = text[a:b]
assert body.count(anchor) == 1, f"anchor appears {body.count(anchor)}x"
open(dst, "w").write(text[:a] + body.replace(anchor, clamp + anchor) + text[b:])
print("  clamp inserted")
PY

echo "diff, stock vs patched:"
diff "$SRC/rtcm3.c" "$T/patched/src/rtcm3.c" | sed 's/^/  /' || true
echo

cd "$HERE"
python3 gen_rtcm.py "$T/benign.bin"   --benign                   >/dev/null
python3 gen_rtcm.py "$T/a211.bin"     --field rectype --len 211  >/dev/null
python3 gen_rtcm.py "$T/a255.bin"     --field rectype --len 255  >/dev/null
python3 gen_rtcm.py "$T/oob.bin"      --field recsno  --len 255  >/dev/null

build() {  # $1=tag $2=srcdir  $3.. extra flags
    local tag=$1 s=$2; shift 2
    gcc -I"$s" -DTRACE -Wno-unused-result -g -O0 -fno-omit-frame-pointer "$@" \
        -o "$T/h-$tag" harness.c \
        "$s/rtcm.c" "$s/rtcm2.c" "$s/rtcm3.c" "$s/rtcm3e.c" "$s/rtkcmn.c" \
        -lm -lpthread
}
build stock   "$SRC"
build clamped "$T/patched/src"
build ubstock  "$SRC"             -fsanitize=undefined
build ubclamp "$T/patched/src"    -fsanitize=undefined

printf '%-10s %-38s %s\n' stream stock clamped
for s in benign a211 a255 oob; do
    a=$("$T/h-stock"   "$T/$s.bin" | grep 'sta.pos' | tail -1 | sed 's/.*= //')
    b=$("$T/h-clamped" "$T/$s.bin" | grep 'sta.pos' | tail -1 | sed 's/.*= //')
    printf '%-10s %-38s %s\n' "$s" "$a" "$b"
done
echo "truth      -2694685.4730 -4293642.3660 3857878.9240"
echo

# Capture rather than pipe to `... || echo`: grep's exit status is masked by
# the pipe, so a broken run would print an empty line and read as "clean".
echo "UBSan on the n1=255 stream -- the control must fire:"
s=$("$T/h-ubstock" "$T/a255.bin" 2>&1 | grep -o 'runtime error.*' | head -1)
c=$("$T/h-ubclamp" "$T/a255.bin" 2>&1 | grep -o 'runtime error.*' | head -1)
echo "  stock:   ${s:-NO FINDING -- control did not fire, the line below means nothing}"
echo "  clamped: ${c:-clean}"
