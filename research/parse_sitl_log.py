#!/usr/bin/env python3
"""
Measure the aircraft's response from a SITL dataflash log.

Reads ground truth (SIM) and the GPS the autopilot was given (GPS) straight
from the .BIN log. This is deliberately not done over MAVLink: streamed
telemetry can stall silently mid-flight, and a frozen ground-truth feed looks
exactly like an aircraft holding perfectly still. The log is written by the
simulator to disk at high rate and does not have that failure mode.

The attack window is identified from the data itself -- the interval where
GPS-reported position departs from truth -- so no clock correlation with the
flight script is needed.

Usage:
    python3 parse_sitl_log.py /tmp/rtk-sitl/logs/00000004.BIN
"""
import argparse
import math
import sys

from pymavlink import mavutil


def ne(dlat, dlon, lat):
    return dlat * 111320.0, dlon * 111320.0 * math.cos(math.radians(lat))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile")
    ap.add_argument("--hold-window", type=float, default=30.0,
                    help="seconds after the glitch that are still position-hold")
    ap.add_argument("--settle", type=float, default=5.0,
                    help="seconds to skip after the glitch before measuring")
    # Must match WP_LAT/WP_LON in ardupilot_demo.py.
    ap.add_argument("--target", type=lambda s: tuple(float(x) for x in s.split(",")),
                    default=(35.160876298 + 30.0 / 111320.0, 139.613834769),
                    help="commanded waypoint 'lat,lon' for the phase-3 check")
    args = ap.parse_args()

    mlog = mavutil.mavlink_connection(args.logfile)

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

    if not sim or not gps:
        sys.exit(f"no SIM ({len(sim)}) or GPS ({len(gps)}) records found")

    print(f"SIM records: {len(sim)}   GPS records: {len(gps)}")
    print(f"log spans {sim[0][0]:.1f}..{sim[-1][0]:.1f} s")

    # For each GPS sample, the nearest truth sample, and the offset between.
    si = 0
    offs = []
    for gt, gla, glo in gps:
        while si + 1 < len(sim) and abs(sim[si + 1][0] - gt) < abs(sim[si][0] - gt):
            si += 1
        st, sla, slo = sim[si]
        dn, de = ne(gla - sla, glo - slo, sla)
        offs.append((gt, math.hypot(dn, de), dn, de))

    # The glitch is a step; find where the GPS-vs-truth offset jumps.
    mags = [o[1] for o in offs]
    lo, hi = min(mags), max(mags)
    if hi - lo < 0.5:
        print(f"\nno GPS/truth divergence found (offset {lo:.2f}..{hi:.2f} m)")
        print("the glitch was probably never applied")
        return 1
    thresh = (lo + hi) / 2.0
    t_attack = next(o[0] for o in offs if o[1] > thresh)
    print(f"\nGPS-vs-truth offset: {lo:.2f} m before, {hi:.2f} m after")
    print(f"attack begins at t={t_attack:.1f}s")

    def truth_window(t0, t1):
        pts = [(la, lo_) for t, la, lo_ in sim if t0 <= t <= t1]
        if not pts:
            return None
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    before = truth_window(t_attack - 20, t_attack - 1)
    # Bound the hold measurement: anything later includes the phase-3 transit
    # and would report the whole leg as a response to the attack.
    after = truth_window(t_attack + args.settle, t_attack + args.hold_window)
    if not before or not after:
        sys.exit("not enough data either side of the glitch")

    dn, de = ne(after[0] - before[0], after[1] - before[1], before[0])
    injected = [o for o in offs if t_attack + args.settle < o[0]
                <= t_attack + args.hold_window]
    inj_n = sum(o[2] for o in injected) / len(injected)
    inj_e = sum(o[3] for o in injected) / len(injected)

    print("\n--- what the AIRCRAFT physically did ---")
    print(f"  injected GPS offset : N={inj_n:+.2f} m  E={inj_e:+.2f} m  "
          f"|{math.hypot(inj_n, inj_e):.2f} m|")
    print(f"  true position moved : N={dn:+.2f} m  E={de:+.2f} m  "
          f"|{math.hypot(dn, de):.2f} m|")

    expected = math.hypot(inj_n, inj_e)
    actual = math.hypot(dn, de)
    print("\n  while holding position (GUIDED):")
    residual = math.hypot(dn + inj_n, de + inj_e)
    if actual < expected * 0.25:
        print("    aircraft did NOT move -- the step was absorbed without a")
        print("    physical correction.")
    elif residual < expected * 0.4:
        print(f"    aircraft moved {actual:.2f} m, opposite the injected offset")
        print(f"    (residual {residual:.2f} m): it repositioned to satisfy a")
        print("    GPS that was lying to it, correcting a drift that never")
        print("    happened.")
    else:
        print(f"    aircraft moved {actual:.2f} m (unclear relationship)")

    # Phase 3: told to fly to a known coordinate while the GPS is lying.
    wp_lat, wp_lon = args.target
    final = truth_window(sim[-1][0] - 20, sim[-1][0] - 5)
    if final:
        en, ee = ne(final[0] - wp_lat, final[1] - wp_lon, wp_lat)
        miss = math.hypot(en, ee)
        print("\n--- navigating to a commanded waypoint ---")
        print(f"  commanded   : {wp_lat:.9f}, {wp_lon:.9f}")
        print(f"  actually at : {final[0]:.9f}, {final[1]:.9f}")
        print(f"  MISS DISTANCE: N={en:+.2f} m E={ee:+.2f} m  |{miss:.2f} m|")
        # Sanity check: a vehicle that never left the hold point will show a
        # "miss" equal to the whole leg length. That is a failed goto, not a
        # navigation error caused by the attack.
        start = truth_window(t_attack + args.settle, t_attack + args.settle + 15)
        flew = 0.0
        if start:
            fn, fe = ne(final[0] - start[0], final[1] - start[1], start[0])
            flew = math.hypot(fn, fe)
        leg = math.hypot(*ne(wp_lat - (start[0] if start else wp_lat),
                             wp_lon - (start[1] if start else wp_lon),
                             wp_lat))
        print(f"  distance actually flown in this phase: {flew:.2f} m "
              f"(leg length {leg:.2f} m)")
        if flew < leg * 0.25:
            print("  => the aircraft never flew the leg; the goto did not")
            print("     execute. This says nothing about the attack.")
        elif miss > expected * 0.5:
            print(f"  => the aircraft flew to a point {miss:.2f} m from where it")
            print("     was told to go, while reporting that it had arrived.")
        else:
            print("  => arrived within tolerance; the offset did not translate")
            print("     into a navigation error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
