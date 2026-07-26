#!/bin/bash
# Does a given RTKLIB fork still carry the type 1033 station-position defect?
#
#   ./check_fork.sh [owner/repo] [branch]
#   ./check_fork.sh                        # defaults to emlid/RTKLIB reach
#   ./check_fork.sh rtklibexplorer/RTKLIB demo5
#
# Three questions, and all three have to hold for the attack to work. A fork
# that fixed any one of them is not vulnerable, and it is worth knowing which:
#
#   1. Is decode_type1033's strncpy still unclamped? (the defect itself)
#   2. Does sta_t still put pos[3] at the same offset? If yes, the payload
#      lengths measured on upstream work here with nothing recomputed.
#   3. Does the real-time path still adopt sta.pos into the baseline without
#      validating it? Upstream guards the post-processing path with norm() and
#      leaves the real-time path bare; forks sometimes inline update_antpos()
#      into updatesvr(), which is why this greps for the assignment rather than
#      the function name.
#
# Reads raw files over HTTPS -- no clone, nothing built, nothing run.
set -u

REPO="${1:-emlid/RTKLIB}"
BR="${2:-reach}"
RAW="https://raw.githubusercontent.com/$REPO/$BR"
W="${TMPDIR:-/tmp}/fork-check-$(echo "$REPO$BR" | tr '/' '-')"
mkdir -p "$W" || exit 1

echo "=== $REPO @ $BR ==="

for f in rtcm3.c rtklib.h rtksvr.c postpos.c; do
    code=$(curl -sS -o "$W/$f" -w '%{http_code}' --max-time 40 "$RAW/src/$f")
    if [ "$code" != "200" ]; then
        echo "  cannot fetch src/$f (HTTP $code) -- wrong branch, or a fork"
        echo "  that restructured the tree. Nothing further can be said."
        exit 1
    fi
done

# ---- 1. the defect ---------------------------------------------------------
echo
echo "1. decode_type1033 -- unclamped copies into fixed-size fields"
DEC=$(awk '/decode_type1033/,/^}/' "$W/rtcm3.c")
if [ -z "$DEC" ]; then
    echo "     decode_type1033 not found -- the message type may be unhandled"
else
    echo "$DEC" | grep -nE 'strncpy' | sed 's/^/     /'
    # rectype is the field that matters: it is the first one that can reach pos.
    if echo "$DEC" | grep -q 'strncpy(rtcm->sta.rectype,rec,n1)'; then
        echo "     VULNERABLE: rectype copied with the wire-supplied length n1"
    elif echo "$DEC" | grep -qE 'rectype.*(sizeof|MAXANT-1|<[0-9]+)'; then
        echo "     looks clamped -- read it, this may be fixed"
    else
        echo "     rectype line not in the expected form; read it by hand"
    fi
fi

# ---- 2. the layout --------------------------------------------------------
echo
echo "2. sta_t layout -- is pos[3] at the same offset as upstream (464)?"
python3 - "$W/rtklib.h" <<'PY'
import re, sys
src = open(sys.argv[1], errors="replace").read()
m = re.search(r'#define\s+MAXANT\s+(\d+)', src)
maxant = int(m.group(1)) if m else None
# Anchor on the closing tag and walk BACK to the nearest opening brace. A
# forward non-greedy match from `typedef struct {` starts at the first struct
# in the header and swallows everything up to `} sta_t;`, so the first `pos[3]`
# it finds belongs to an ephemeris struct and the offset comes out as 72.
end = src.find('} sta_t;')
starts = [m.start() for m in re.finditer(r'typedef struct \{', src[:end])] if end > 0 else []
body = src[starts[-1]:end] if (starts and maxant) else None
if not (maxant and body):
    print("     could not parse MAXANT or sta_t"); sys.exit()
print(f"     MAXANT = {maxant}")
off, poso = 0, None
for line in body.splitlines():
    line = re.sub(r'/\*.*?\*/', '', line).strip().rstrip(';')
    if not line:
        continue
    mm = re.match(r'(char|int|double)\s+(.*)', line)
    if not mm:
        continue
    ctype, names = mm.group(1), mm.group(2)
    size = {"char": 1, "int": 4, "double": 8}[ctype]
    for name in names.split(','):
        name = name.strip()
        if not name:
            continue
        arr = re.findall(r'\[([^\]]+)\]', name)
        n = 1
        for a in arr:
            n *= maxant if 'MAXANT' in a else (int(a) if a.strip().isdigit() else 1)
        if size > 1 and off % size:            # natural alignment
            off += size - (off % size)
        if name.startswith('pos') and ctype == 'double' and poso is None:
            poso = off
        off += size * n
print(f"     computed offsetof(sta_t,pos) = {poso}")
print("     MATCHES upstream x86-64: the measured payload lengths transfer unchanged"
      if poso == 464 else
      f"     DIFFERS from upstream (464): recompute the length thresholds for this target")
PY

# ---- 3. the adoption ------------------------------------------------------
echo
echo "3. real-time adoption of sta.pos into the baseline"
ADOPT=$(grep -nE 'rtk\.rb\[i\] *= *.*sta\.pos|rb\[i\] *= *sta->pos' "$W/rtksvr.c")
if [ -n "$ADOPT" ]; then
    echo "$ADOPT" | sed 's/^/     /'
    echo "     -> present. Check for a guard on the lines above:"
    grep -nE 'norm\(.*sta.*pos|POSOPT_RTCM' "$W/rtksvr.c" | head -4 | sed 's/^/        /'
    grep -qE 'norm\(.*sta.*pos' "$W/rtksvr.c" \
        && echo "     a norm() guard exists here -- read it" \
        || echo "     UNGUARDED: no plausibility check on the adopted coordinate"
else
    echo "     no direct sta.pos -> rtk.rb assignment found in rtksvr.c"
fi

echo
echo "   (for contrast, the post-processing path in postpos.c:)"
grep -n 'norm(.*sta\[' "$W/postpos.c" | head -2 | sed 's/^/     /'
