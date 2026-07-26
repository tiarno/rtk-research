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
    alt = []
    while True:
        m = mlog.recv_match(type=["SIM", "GPS"])
        if m is None:
            break
        t = getattr(m, "TimeUS", None)
        if t is None:
            continue
        if m.get_type() == "SIM":
            a = getattr(m, "Alt", None)
            sim.append((t / 1e6, m.Lat, m.Lng, a))
            if a is not None:
                alt.append((t / 1e6, a))
        elif getattr(m, "I", 0) == 0 and getattr(m, "Status", 0) >= 3:
            gps.append((t / 1e6, m.Lat, m.Lng, getattr(m, "Alt", None)))

    if not sim or not gps:
        sys.exit(f"no SIM ({len(sim)}) or GPS ({len(gps)}) records found")

    print(f"SIM records: {len(sim)}   GPS records: {len(gps)}")
    print(f"log spans {sim[0][0]:.1f}..{sim[-1][0]:.1f} s")

    # For each GPS sample, the nearest truth sample, and the offset between.
    #
    # The vertical is carried alongside but never folded into the magnitude the
    # onset detector uses. A corrupted base coordinate moves the solution in all
    # three axes, and roughly a third of the ECEF error lands in height -- but
    # the aircraft's altitude comes mostly from its barometer, so mixing the
    # vertical into the horizontal would compare two quantities the autopilot
    # weighs completely differently.
    si = 0
    offs = []
    for gt, gla, glo, gz in gps:
        while si + 1 < len(sim) and abs(sim[si + 1][0] - gt) < abs(sim[si][0] - gt):
            si += 1
        st, sla, slo, sz = sim[si]
        dn, de = ne(gla - sla, glo - slo, sla)
        dz = (gz - sz) if (gz is not None and sz is not None) else None
        offs.append((gt, math.hypot(dn, de), dn, de, dz))

    # Find where the GPS-vs-truth offset steps -- and stays stepped.
    #
    # An instantaneous threshold crossing is not enough: while the aircraft
    # flies a leg, its GPS lags its true position by a metre or two, so a
    # perfectly clean control run shows a 3 m transient spike during the goto
    # and gets read as an attack. The injected offset is *sustained*, so
    # require the median offset over the whole measurement window to be
    # elevated, which a few seconds of transit lag cannot fake.
    def fwd_median(i, span):
        w = [o[1] for o in offs[i:] if o[0] <= offs[i][0] + span]
        return sorted(w)[len(w) // 2] if w else 0.0

    span = args.hold_window
    med = [fwd_median(i, span) for i in range(len(offs))]
    # `lo` from the instantaneous offsets, `hi` from the sustained ones: a
    # transit spike must not set the scale. The onset is then the first
    # instantaneous crossing that is also sustained -- taking the first
    # crossing of the *median* instead would place it half a window early,
    # because a window straddling the step is already half elevated.
    lo, hi = min(o[1] for o in offs), max(med)
    t_attack = None
    if hi - lo >= 0.5:
        thresh = (lo + hi) / 2.0
        t_attack = next((o[0] for o, mv in zip(offs, med)
                         if o[1] > thresh and mv > thresh), None)

    if t_attack is None:
        if lo > 0.5:
            # No step anywhere, but the rover never agreed with truth either.
            print(f"\n*** GPS is offset from truth by {lo:.2f}..{hi:.2f} m for "
                  "the ENTIRE log.")
            print("*** The attack predates the log, so there is no clean")
            print("*** baseline in it and no displacement can be attributed.")
            print("*** Re-run with the relay released by the flight driver.")
        else:
            print(f"\nno sustained GPS/truth divergence (offset {lo:.2f} m, "
                  f"sustained max {hi:.2f} m)")
            print("nothing was injected, or the injection never reached the "
                  "rover")
    else:
        print(f"\nGPS-vs-truth offset: {lo:.2f} m before, {hi:.2f} m after")
        print(f"attack begins at t={t_attack:.1f}s")

    # The attack must land on an aircraft that is already flying and already
    # holding a target captured from a clean position. If it arrives during
    # takeoff, the hold target is captured from an offset the GPS is already
    # reporting, and the displacement measured below is a takeoff transient
    # anchored to a lie rather than a response to one. That happened, and it
    # is what made the closed-loop displacement disagree in sign with the
    # open-loop run -- see research/README.md.
    airborne = None
    if alt:
        ground = alt[0][1]
        airborne = next((t for t, a in alt if a - ground > 0.5), None)
    if t_attack is not None and airborne is not None:
        if t_attack < airborne:
            print(f"\n*** the GPS started lying at t={t_attack:.1f}s but the "
                  f"aircraft did not leave the ground until t={airborne:.1f}s.")
            print("*** There was no clean flight phase. The hold target was")
            print("*** captured from an already-corrupted position, so the")
            print("*** displacement below is NOT a response to the attack.")
            print("*** Do not quote it. Re-run: the relay must be released by")
            print("*** the flight driver (--trigger), not by a timer.")
        else:
            print(f"(airborne at t={airborne:.1f}s, "
                  f"{t_attack - airborne:.0f}s before the attack)")

    def truth_window(t0, t1):
        """Mean truth position over a window: (lat, lon, alt). `alt` is None if
        the log carried no SIM altitude, and callers must tolerate that."""
        pts = [(la, lo_, az) for t, la, lo_, az in sim if t0 <= t <= t1]
        if not pts:
            return None
        zs = [p[2] for p in pts if p[2] is not None]
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts),
                (sum(zs) / len(zs)) if zs else None)

    expected = 0.0
    if t_attack is not None:
        before = truth_window(t_attack - 20, t_attack - 1)
        # Bound the hold measurement: anything later includes the phase-3
        # transit and would report the whole leg as a response to the attack.
        after = truth_window(t_attack + args.settle,
                             t_attack + args.hold_window)
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

        # Vertical, reported separately and never mixed into the horizontal.
        inj_z = [o[4] for o in injected if o[4] is not None]
        pre_z = [o[4] for o in offs
                 if o[4] is not None and t_attack - 20 <= o[0] <= t_attack - 1]
        if inj_z and pre_z and before[2] is not None and after[2] is not None:
            vz_before = sum(pre_z) / len(pre_z)
            vz_after = sum(inj_z) / len(inj_z)
            dz_true = after[2] - before[2]
            print(f"\n  vertical, measured separately:")
            print(f"    GPS height error    : {vz_before:+.2f} m before -> "
                  f"{vz_after:+.2f} m during")
            print(f"    true height moved   : {dz_true:+.2f} m")
            step = vz_after - vz_before
            if abs(step) < 0.25:
                print("    the height solution barely moved -- nothing to respond to.")
            elif abs(dz_true) < abs(step) * 0.25:
                print(f"    the aircraft did NOT follow it ({abs(dz_true):.2f} m "
                      f"against a {abs(step):.2f} m lie).")
                print("    Expected: ArduPilot's EKF takes height from the")
                print("    barometer by default, so a corrupted GPS height is")
                print("    largely ignored. The horizontal has no such second")
                print("    source, which is why only it moves the aircraft.")
            else:
                print(f"    the aircraft followed it by {dz_true:+.2f} m against "
                      f"a {step:+.2f} m lie -- height IS being fused.")
        else:
            print("\n  vertical: not measurable from this log "
                  "(no SIM/GPS altitude pair)")

        expected = math.hypot(inj_n, inj_e)
        actual = math.hypot(dn, de)
        print("\n  while holding position (GUIDED):")
        residual = math.hypot(dn + inj_n, de + inj_e)
        if actual < expected * 0.25:
            print("    aircraft did NOT move -- the step was absorbed without a")
            print("    physical correction.")
        elif residual < expected * 0.4:
            print(f"    aircraft moved {actual:.2f} m, opposite the injected "
                  "offset")
            print(f"    (residual {residual:.2f} m): it repositioned to satisfy a")
            print("    GPS that was lying to it, correcting a drift that never")
            print("    happened.")
        else:
            print(f"    aircraft moved {actual:.2f} m (unclear relationship)")

    # Phase 3: told to fly to a known coordinate while the GPS is lying.
    #
    # Deliberately independent of the attack time, so a control run with no
    # injection at all is measured exactly the same way -- that comparison is
    # the whole point of running one.
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
        # navigation error caused by the attack. The leg is taken from where
        # the aircraft was furthest from the waypoint -- the hold point, in
        # this profile -- rather than from the attack time, which the control
        # run does not have.
        cand = [(t, la, lo_) for t, la, lo_, _z in sim if t <= sim[-1][0] - 20]
        far = max(cand, key=lambda p: math.hypot(
            *ne(p[1] - wp_lat, p[2] - wp_lon, wp_lat))) if cand else None
        start = truth_window(far[0] - 5, far[0]) if far else None
        flew = 0.0
        if start:
            fn, fe = ne(final[0] - start[0], final[1] - start[1], start[0])
            flew = math.hypot(fn, fe)
        leg = math.hypot(*ne(wp_lat - (start[0] if start else wp_lat),
                             wp_lon - (start[1] if start else wp_lon),
                             wp_lat))
        print(f"  distance actually flown in this phase: {flew:.2f} m "
              f"(leg length {leg:.2f} m)")
        if leg > 1.0 and flew < leg * 0.25:
            print("  => the aircraft never flew the leg; the goto did not")
            print("     execute. This says nothing about the attack.")
        elif t_attack is None:
            print(f"  => control run: flew the leg and arrived within "
                  f"{miss:.2f} m.")
        elif miss > expected * 0.5:
            print(f"  => the aircraft flew to a point {miss:.2f} m from where it")
            print("     was told to go, while reporting that it had arrived.")
        else:
            print("  => arrived within tolerance; the offset did not translate")
            print("     into a navigation error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
