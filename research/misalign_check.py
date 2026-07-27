#!/usr/bin/env python3
"""
A second defect in decode_type1033: a declared length above 31 misaligns every
field parsed after it.

The five length bytes are read with absolute bit offsets computed from the
declared lengths, so those are always correct:

    n =getbitu(rtcm->buff,i+12,8);
    m =getbitu(rtcm->buff,i+28+8*n,8);
    ...

But the sequential walk that follows advances `i` by at most 31 bytes per
field, while the wire format carries the full declared length:

    for (j=0;j<n&&j<31;j++) { des[j]=getbitu(rtcm->buff,i,8); i+=8; }
    setup=getbitu(rtcm->buff,i, 8); i+=8+8;

So any declared length above 31 leaves the walk short by (len-31) bytes, and
everything read after that field comes from the wrong offset.

This is separate from the overflow and unaffected by clamping the copy lengths
-- the clamp stops the write, not the walk. It also does NOT affect the
station-position attack, which oversizes `rectype`: everything that attack
depends on is parsed before the walk reaches that field. It bites when an
EARLIER field is oversized.

Two streams, identical except for the antenna descriptor length:

    antdes = 20 bytes   within the 31-byte cap, walk stays aligned   (control)
    antdes = 40 bytes   9 bytes past it

Usage:
    ./misalign_check.py                 # generate streams, run ./harness
    ./misalign_check.py --no-run        # generate only
    OUT=/tmp/x ./misalign_check.py      # somewhere other than /tmp/rtk-misalign

Needs ./harness built first:  RTKLIB=<checkout> ./build.sh
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gen_rtcm import msg1005, msg1033  # noqa: E402

# Distinctive and different lengths, so a shifted read is obvious on sight
# rather than something you have to diff.
COMMON = dict(
    antsno=b"SNO-ALPHA",
    rectype=b"TRIMBLE NETR9",
    recver=b"5.22",
    recsno=b"RSN-OMEGA",
    setup=7,
)

CASES = [
    ("short", 20),   # control
    ("long",  40),   # 9 past the staging cap
]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-run", action="store_true",
                    help="write the streams but do not invoke ./harness")
    args = ap.parse_args()

    out = os.environ.get("OUT", "/tmp/rtk-misalign")
    os.makedirs(out, exist_ok=True)

    paths = []
    for name, n in CASES:
        stream = msg1005() + msg1033(antdes=b"D" * n, **COMMON)
        path = os.path.join(out, f"{name}.bin")
        with open(path, "wb") as fh:
            fh.write(stream)
        paths.append((name, n, path))
        print(f"{name}.bin: antdes={n}B  stream={len(stream)}B")

    print()
    print("what a correct parse yields, in both cases:")
    print(f"  antsetup = {COMMON['setup']}")
    for k in ("antsno", "rectype", "recver", "recsno"):
        print(f"  {k:<9}= {COMMON[k].decode()}")

    if args.no_run:
        return 0

    harness = os.path.join(HERE, "harness")
    if not os.path.isfile(harness):
        print(f"\nno {harness} -- build it first:", file=sys.stderr)
        print("  RTKLIB=<checkout> ./build.sh", file=sys.stderr)
        return 1

    print()
    for name, n, path in paths:
        print(f"======== {name}.bin (antdes={n}) ========")
        res = subprocess.run([harness, path], capture_output=True, text=True)
        # the second message is the 1033; report what it decoded to
        block = res.stdout.split("message 2:")[-1]
        for line in block.splitlines():
            if any(f in line for f in ("antdes", "rectype", "recsno",
                                       "antsetup")):
                print("  " + line.strip())
        print()

    print("The control decodes every field correctly. In the 40-byte case the")
    print("field LENGTHS are still right -- they come from the absolute-offset")
    print("reads -- but the contents are displaced by exactly 9 bytes, and")
    print("antsetup reads 68 (0x44, 'D'): the 32nd descriptor byte.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
