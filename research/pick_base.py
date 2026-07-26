#!/usr/bin/env python3
"""
Choose a base-station ECEF X for the demo, and show what each n1 rung does to it.

The 1033 overflow zeroes low-order bytes of pos[0]. Each extra byte multiplies
the truncation quantum by 256, so the usable settings are a handful of rungs
rather than a dial:

    n1=210   3 bytes   ~8 mm      too small to see
    n1=211   4 bytes   2 m        bounded against ANY base -- the useful one
    n1=212   5 bytes   512 m      a coin toss; usually rejected outright
    n1=213   6 bytes   131 km     gone

Within a rung the error is whatever the truncated low bits happen to be, so the
attacker picks the scale and not the value. For a demo that is a problem: at the
original base -3978242.4348 the reliable rung (211) yields 0.43 m, which is
correct, universal and invisible from the back of a room.

Since the demo's base coordinate is ours to choose, site it instead. This finds
a coordinate near a given one where the chosen rung produces a large error --
and, importantly, reports the margin to the lattice boundary. Sitting 0.2 mm
below a boundary maximises the error and is a terrible idea: any sub-millimetre
shift anywhere in the encode/decode path drops it to ~0 and the demo silently
shows nothing. --margin defends against that.

    ./pick_base.py                          # explain the current demo base
    ./pick_base.py --near -3978242.4348 --n1 211 --margin 0.2
    ./pick_base.py --explain -3978243.8000  # what every rung does to this base

Whatever is chosen, say on the slide that it was chosen: at an arbitrary real
base the n1=211 error is uniform in [0, quantum) with a mean of half of it. The
guarantee is the bound, not the number.
"""
import argparse
import struct

# Bytes of pos[0] zeroed = n1 - 207 (the write starts at rectype+31, pos is at
# offset 464, rectype at 256, and rectype[n1] gets an explicit NUL).
FIRST_N1 = 208


def truncate(x, nbytes):
    """Zero the low `nbytes` bytes of the double, as strncpy's zero padding does."""
    raw = bytearray(struct.pack("<d", x))
    for i in range(min(nbytes, 8)):
        raw[i] = 0
    return struct.unpack("<d", bytes(raw))[0]


def rung(x, n1):
    nb = n1 - (FIRST_N1 - 1)
    t = truncate(x, nb)
    return nb, t, abs(t - x)


def quantum(x, n1):
    """Lattice spacing at this rung: 2**(8*nbytes) * ulp(x)."""
    nb = n1 - (FIRST_N1 - 1)
    lo = truncate(x, nb)
    return abs(truncate(lo - abs(x) * 1e-12, nb) - lo) or 2.0 ** (8 * nb) * ulp(x)


def ulp(x):
    a = struct.unpack("<Q", struct.pack("<d", x))[0]
    return abs(struct.unpack("<d", struct.pack("<Q", a + 1))[0] - x)


def explain(x):
    print(f"base ECEF X = {x:.4f}")
    print(f"  {'n1':<6}{'bytes':<7}{'quantum':<14}{'result':<18}error")
    for n1 in range(208, 215):
        nb, t, err = rung(x, n1)
        q = 2.0 ** (8 * nb) * ulp(x)
        note = "  <- bounded against any base" if n1 == 211 else ""
        print(f"  {n1:<6}{nb:<7}{q:<14.6g}{t:<18.4f}{err:.4f} m{note}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--explain", type=float, metavar="X",
                    help="show what every rung does to this coordinate")
    ap.add_argument("--near", type=float, default=-3978242.4348,
                    help="search for a base near this X")
    ap.add_argument("--n1", type=int, default=211,
                    help="the rung to optimise for (default 211)")
    ap.add_argument("--margin", type=float, default=0.2,
                    help="metres of safety between the error and the lattice "
                         "boundary; 0 maximises the error and is fragile")
    ap.add_argument("--window", type=float, default=3.0,
                    help="how far the site may move, in metres")
    args = ap.parse_args()

    if args.explain is not None:
        explain(args.explain)
        return

    q = 2.0 ** (8 * (args.n1 - FIRST_N1 + 1)) * ulp(args.near)
    target = q - args.margin
    print(f"rung n1={args.n1}: quantum {q:.4g} m")
    print(f"aiming for an error of {target:.4f} m "
          f"({args.margin:.3f} m clear of the boundary)\n")

    best = None
    for i in range(int(args.window * 1000)):        # 1 mm steps
        cand = args.near - i * 0.001
        err = rung(cand, args.n1)[2]
        score = abs(err - target)
        if best is None or score < best[0]:
            best = (score, cand, err)
    _, x, err = best

    print(f"chosen X = {x:.4f}")
    print(f"  error at n1={args.n1}: {err:.4f} m   "
          f"(boundary is {q - err:.4f} m away)")
    print(f"  site moves {abs(x - args.near):.3f} m from --near\n")
    explain(x)
    print(f"\nBASE_ECEF={x:.4f},<Y>,<Z>   # for loop_demo.sh")
    print("Remember to say on the slide that the site was chosen for "
          "visibility:\nat an arbitrary base this rung gives a uniform draw in "
          f"[0, {q:.3g}) m.")


if __name__ == "__main__":
    main()
