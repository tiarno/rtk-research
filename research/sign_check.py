#!/usr/bin/env python3
"""
Which way did the aircraft actually move, and why?

`parse_sitl_log.py` reports magnitudes and one sign test. This prints the
geometry underneath it: truth and reported GPS position in the same local
frame, sampled across the attack window, so the sign of the physical
displacement can be read off rather than inferred.

A vehicle commanded to hold at point H, given a GPS that reports (truth + D),
moves until the *reported* position reads H. That is truth = H - D:

    GPS-reported position stays put;  truth moves by -D.

Both the open-loop run (SIM_GPS1_GLTCH_*) and the closed loop (corrupted base
coordinate) show that, because in both the reported position is truth + D for
a constant D. This was written to settle an apparent disagreement between them
and did: the closed loop's hold target had been captured from an already-
corrupted position, because the relay armed on a timer that beat the aircraft
off the ground. With the relay released by the flight driver instead, the two
runs agree to 7 cm per component.

Reading the columns: `truth` is where the aircraft actually is, `gps` is what
RTKLIB told it, and their difference is D. If D is present before the aircraft
leaves the ground, the run measures nothing -- stop and re-run.

Usage:
    python3 sign_check.py /tmp/rtk-loop/logs/00000008.BIN
    python3 sign_check.py /tmp/rtk-sitl/logs/00000010.BIN --hold-window 30
"""
import argparse
import math
import sys

from pymavlink import mavutil

# Same convention as parse_sitl_log.py: degrees -> metres, north/east.
M_PER_DEG = 111320.0


def ne(dlat, dlon, lat):
    return dlat * M_PER_DEG, dlon * M_PER_DEG * math.cos(math.radians(lat))


def read_log(path):
    mlog = mavutil.mavlink_connection(path)
    sim, gps = [], []
    while True:
        m = mlog.recv_match(type=["SIM", "GPS"])
        if m is None:
            break
        t = getattr(m, "TimeUS", None)
        if t is None:
            continue
        if m.get_type() == "SIM":
            sim.append((t / 1e6, m.Lat, m.Lng))
        elif getattr(m, "I", 0) == 0 and getattr(m, "Status", 0) >= 3:
            gps.append((t / 1e6, m.Lat, m.Lng))
    return sim, gps


def pair(sim, gps):
    """Each GPS sample with its nearest truth sample."""
    si = 0
    out = []
    for gt, gla, glo in gps:
        while si + 1 < len(sim) and abs(sim[si + 1][0] - gt) < abs(sim[si][0] - gt):
            si += 1
        _, sla, slo = sim[si]
        out.append((gt, sla, slo, gla, glo))
    return out


def mean_window(rows, t0, t1, cols):
    sel = [r for r in rows if t0 <= r[0] <= t1]
    if not sel:
        return None
    return tuple(sum(r[c] for r in sel) / len(sel) for c in cols)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--hold-window", type=float, default=30.0)
    ap.add_argument("--settle", type=float, default=5.0)
    ap.add_argument("--step", type=float, default=2.0,
                    help="seconds between printed samples")
    args = ap.parse_args()

    sim, gps = read_log(args.logfile)
    if not sim or not gps:
        sys.exit(f"no SIM ({len(sim)}) or GPS ({len(gps)}) records found")
    rows = pair(sim, gps)

    # Attack onset: the step in |GPS - truth|.
    mags = []
    for t, sla, slo, gla, glo in rows:
        dn, de = ne(gla - sla, glo - slo, sla)
        mags.append((t, math.hypot(dn, de), dn, de))
    lo = min(m[1] for m in mags)
    hi = max(m[1] for m in mags)
    if hi - lo < 0.5:
        print(f"no GPS/truth divergence (offset {lo:.2f}..{hi:.2f} m) -- "
              "control run, nothing to sign")
        t_attack = None
    else:
        thresh = (lo + hi) / 2.0
        t_attack = next(m[0] for m in mags if m[1] > thresh)
        print(f"attack begins at t={t_attack:.1f}s "
              f"(GPS-vs-truth {lo:.2f} m -> {hi:.2f} m)")

    # Local frame anchored on truth just before the attack, so both traces are
    # readable as displacements from the pre-attack hold point.
    t_ref = t_attack if t_attack is not None else rows[len(rows) // 2][0]
    ref = mean_window(rows, t_ref - 20, t_ref - 1, (1, 2))
    if ref is None:
        sys.exit("not enough data before the attack")
    lat0, lon0 = ref

    print(f"\nframe origin = truth mean over t={t_ref - 20:.0f}..{t_ref - 1:.0f}s "
          f"({lat0:.9f}, {lon0:.9f})")
    print("\n    t     truth_N  truth_E    gps_N   gps_E    (gps-truth)_N  _E")
    t_next = rows[0][0]
    for t, sla, slo, gla, glo in rows:
        if t < t_next:
            continue
        t_next = t + args.step
        tn, te = ne(sla - lat0, slo - lon0, lat0)
        gn, ge = ne(gla - lat0, glo - lon0, lat0)
        mark = ""
        if t_attack is not None:
            mark = " <-- attack" if abs(t - t_attack) < args.step / 2 else ""
        print(f"{t:7.1f}  {tn:8.2f} {te:8.2f}  {gn:8.2f} {ge:8.2f}   "
              f"{gn - tn:8.2f} {ge - te:7.2f}{mark}")

    if t_attack is None:
        return 0

    # The three vectors, in one frame.
    before_t = mean_window(rows, t_attack - 20, t_attack - 1, (1, 2))
    after_t = mean_window(rows, t_attack + args.settle,
                          t_attack + args.hold_window, (1, 2))
    before_g = mean_window(rows, t_attack - 20, t_attack - 1, (3, 4))
    after_g = mean_window(rows, t_attack + args.settle,
                          t_attack + args.hold_window, (3, 4))
    if not after_t or not after_g:
        sys.exit("not enough data after the attack")

    inj = [m for m in mags
           if t_attack + args.settle < m[0] <= t_attack + args.hold_window]
    dn_i = sum(m[2] for m in inj) / len(inj)
    de_i = sum(m[3] for m in inj) / len(inj)

    dn_t, de_t = ne(after_t[0] - before_t[0], after_t[1] - before_t[1], lat0)
    dn_g, de_g = ne(after_g[0] - before_g[0], after_g[1] - before_g[1], lat0)

    print(f"\n--- vectors over t={t_attack + args.settle:.0f}"
          f"..{t_attack + args.hold_window:.0f}s vs. the 20 s before ---")
    print(f"  D, injected GPS offset (gps-truth) : "
          f"N={dn_i:+.2f} E={de_i:+.2f}  |{math.hypot(dn_i, de_i):.2f} m|")
    print(f"  truth moved                        : "
          f"N={dn_t:+.2f} E={de_t:+.2f}  |{math.hypot(dn_t, de_t):.2f} m|")
    print(f"  reported (GPS) position moved      : "
          f"N={dn_g:+.2f} E={de_g:+.2f}  |{math.hypot(dn_g, de_g):.2f} m|")

    res = math.hypot(dn_t + dn_i, de_t + de_i)
    same = math.hypot(dn_t - dn_i, de_t - de_i)
    print(f"\n  |truth_move + D| = {res:.2f} m   (0 => moved OPPOSITE D, "
          "as a correcting loop should)")
    print(f"  |truth_move - D| = {same:.2f} m   (0 => moved WITH D)")
    if res < same:
        print("  => OPPOSITE the injected offset: it repositioned to correct a "
              "drift that never happened.")
    else:
        print("  => WITH the injected offset.")
    print(f"\n  reported position held to {math.hypot(dn_g, de_g):.2f} m of the "
          "hold point while truth moved --")
    print("  the loop is closing on the GPS it is being fed, not on truth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
