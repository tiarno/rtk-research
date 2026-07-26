#!/usr/bin/env python3
"""
Measure the closed loop's delay: a fed rover position out to an NMEA sentence.

In `loop_demo.sh` the autopilot steers on a solution computed from its own
position, so the whole round trip -- position feed, observable synthesis, RTCM3
encode, on-path relay, RTKLIB, NMEA out -- sits inside the vehicle's control
loop. A real GPS presents a delay of roughly 200 ms and ArduPilot's EKF is
built for that. If this pipeline is much slower, the vehicle oscillates whether
or not anything is attacking it, and no distance measured in the loop means
anything.

The vehicle is deliberately absent here. A square wave in latitude goes in, the
same square wave comes out the far end, and the lag between the two edges is
the number. Nothing can destabilise, so the measurement is clean.

    feed    : emit "lat,lon,height" at <rate> Hz, stepping latitude
              periodically (or ramping, with --ramp)
    read    : connect to RTKLIB's NMEA server and timestamp every GGA
    analyse : pair the edges from both logs and report the delay
    speed   : check the reported ground speed against a fed constant ramp

Driven by loop_latency.sh -- `MODE=speed ./loop_latency.sh` for the last one.
"""
import argparse
import math
import socket
import sys
import time

M_PER_DEG = 111320.0
KNOT2MS = 1852.0 / 3600.0


def cmd_feed(args):
    """Square wave in latitude, one edge every --period seconds.

    With --ramp, a constant northward speed instead: the input the `speed`
    subcommand checks the reported ground speed against.
    """
    events = open(args.events, "w", buffering=1)
    events.write("unix,lat\n")
    lat0, lon, hgt = args.lat, args.lon, args.height
    period = 1.0 / args.rate
    high = False
    t0 = last_edge = time.time()
    next_tick = t0

    while True:
        now = time.time()
        if args.ramp:
            # --ramp-dir 0 is due north, 90 due east. Testing off-north
            # matters: outnmea_rmc() holds its previous course below 1 m/s,
            # and its initial held value is 0.0, so a northward ramp reports
            # the right course for the wrong reason.
            d = math.radians(args.ramp_dir)
            dn = args.ramp * math.cos(d) * (now - t0)
            de = args.ramp * math.sin(d) * (now - t0)
            lat = lat0 + dn / M_PER_DEG
            lon = args.lon + de / (M_PER_DEG * math.cos(math.radians(lat0)))
        else:
            if now - last_edge >= args.period:
                high = not high
                last_edge = now
                lat = lat0 + (args.amp / M_PER_DEG if high else 0.0)
                events.write(f"{now:.3f},{lat:.9f}\n")
            lat = lat0 + (args.amp / M_PER_DEG if high else 0.0)
        print(f"{lat:.9f},{lon:.9f},{hgt:.4f}", flush=True)
        next_tick += period
        if args.seconds and now - t0 > args.seconds:
            break
        time.sleep(max(0.0, next_tick - time.time()))


def rmc_speed(line):
    """Ground speed in m/s and course in degrees from an RMC sentence."""
    f = line.split(",")
    if len(f) < 9 or not f[0].endswith("RMC") or f[1] == "":
        return None
    try:
        return float(f[7]) * KNOT2MS, float(f[8]) if f[8] else None
    except ValueError:
        return None


def cmd_speed(args):
    """
    Does the RMC report the speed the rover is actually doing?

    RTKLIB's own NMEA writer says 0.00 knots however fast the rover moves,
    because the rtksvr path leaves the solution velocity at zero. The harness
    fills it in by differencing (NMEA_VEL=1). Feed a known ramp, read the far
    end, compare.
    """
    host, port = args.connect.rsplit(":", 1)
    deadline = time.time() + args.seconds
    speeds, courses, quals = [], [], []
    try:
        s = socket.create_connection((host or "127.0.0.1", int(port)),
                                     timeout=10)
    except OSError as e:
        print(f"connect failed: {e}")
        return 1
    s.settimeout(2.0)
    buf = b""
    while time.time() < deadline:
        try:
            data = s.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode("ascii", "replace").strip()
            got = rmc_speed(line)
            if got is not None:
                speeds.append(got[0])
                if got[1] is not None:
                    courses.append(got[1])
            f = line.split(",")
            if f[0].endswith("GGA") and len(f) > 6 and f[6]:
                quals.append(int(f[6]))
    s.close()

    if not speeds:
        print("no RMC sentences arrived")
        return 1
    # Drop the first few: the differencing window has to fill, and the ramp
    # takes a moment to reach the far end.
    warm = speeds[args.skip:]
    if not warm:
        print(f"only {len(speeds)} RMC sentences, all inside the warm-up")
        return 1
    warm.sort()
    med = warm[len(warm) // 2]
    mean = sum(warm) / len(warm)
    print(f"RMC sentences: {len(speeds)} ({len(warm)} after warm-up)")
    print(f"reported speed: median {med:.3f} m/s  mean {mean:.3f} m/s  "
          f"min {warm[0]:.3f}  max {warm[-1]:.3f}")
    course_bad = False
    if courses:
        cs = sorted(courses[args.skip:] or courses)
        cmed = cs[len(cs) // 2]
        err = (cmed - args.expect_course + 180.0) % 360.0 - 180.0
        course_bad = abs(err) > 10.0
        print(f"reported course: median {cmed:.1f} deg, fed "
              f"{args.expect_course:.1f} deg, error {err:+.1f} deg"
              + ("   <-- WRONG" if course_bad else ""))
    if quals:
        print(f"GGA quality: {sorted(set(quals))} over {len(quals)} sentences")
    print(f"\nfed {args.expect:.3f} m/s")
    err = med - args.expect
    if args.expect == 0.0:
        ok = abs(med) < 0.1
    else:
        ok = abs(err) < 0.15 * args.expect
    print(f"error {err:+.3f} m/s -- "
          + ("speed is usable" if ok else "speed NOT usable"))
    if course_bad:
        # ArduPilot rebuilds the velocity vector as speed x course, so a wrong
        # course is a wrong velocity however good the speed is -- and a course
        # that is *stuck* is worse than a noisy one, because the EKF chases a
        # consistent bias instead of averaging out noise.
        print("course is wrong: the velocity vector an autopilot rebuilds "
              "from this points\nthe wrong way, which destabilises a hover "
              "even though the speed is right")
    return 0 if (ok and not course_bad) else 1


def gga_lat(line):
    """Latitude in degrees from a GGA sentence, or None."""
    f = line.split(",")
    if len(f) < 4 or not f[0].endswith("GGA") or not f[2]:
        return None
    deg = float(f[2][:2]) + float(f[2][2:]) / 60.0
    return -deg if f[3] == "S" else deg


def cmd_read(args):
    """Timestamp each GGA as it arrives from RTKLIB."""
    host, port = args.connect.rsplit(":", 1)
    deadline = time.time() + args.seconds
    out = open(args.samples, "w", buffering=1)
    out.write("unix,lat\n")
    n = 0
    while time.time() < deadline:
        try:
            s = socket.create_connection((host or "127.0.0.1", int(port)),
                                         timeout=5)
        except OSError as e:
            print(f"connect failed: {e}, retrying", file=sys.stderr)
            time.sleep(1)
            continue
        buf = b""
        s.settimeout(2.0)
        while time.time() < deadline:
            try:
                data = s.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                lat = gga_lat(line.decode("ascii", "replace").strip())
                if lat is not None:
                    out.write(f"{time.time():.3f},{lat:.9f}\n")
                    n += 1
        s.close()
    print(f"{n} GGA sentences", file=sys.stderr)


def edges(rows, mid):
    """Times at which the series crosses `mid`, with direction."""
    out = []
    for (_, prev), (t, cur) in zip(rows, rows[1:]):
        if (prev < mid) != (cur < mid):
            out.append((t, cur > prev))
    return out


def load(path):
    rows = []
    with open(path) as fp:
        next(fp, None)
        for line in fp:
            t, lat = line.split(",")
            rows.append((float(t), float(lat)))
    return rows


def cmd_analyse(args):
    fed, got = load(args.events), load(args.samples)
    if len(fed) < 2 or len(got) < 4:
        print(f"not enough data: {len(fed)} fed edges, {len(got)} samples")
        return 1

    lats = sorted(r[1] for r in got)
    lo, hi = lats[len(lats) // 20], lats[-len(lats) // 20 - 1]
    mid = (lo + hi) / 2.0
    if (hi - lo) * M_PER_DEG < 0.5:
        print("output never moved -- the chain is not carrying the position")
        return 1

    got_edges = edges(got, mid)
    # Every row of the fed log IS an edge; its direction is which level it
    # moved to, so it can be matched against the crossings seen on the way out.
    fed_lats = [lat for _, lat in fed]
    fed_mid = (min(fed_lats) + max(fed_lats)) / 2.0
    fed_edges = [(t, lat > fed_mid) for t, lat in fed]

    print(f"fed {len(fed_edges)} edges, saw {len(got_edges)} in the NMEA output")
    print(f"step amplitude out: {(hi - lo) * M_PER_DEG:.2f} m\n")

    print(f"{'fed at':>10} {'seen at':>10} {'delay':>8}")
    delays = []
    for t_fed, up in fed_edges:
        later = [t for t, u in got_edges if u == up and t >= t_fed - 0.2]
        if not later:
            continue
        d = later[0] - t_fed
        if d > args.max_delay:      # unpaired edge, do not average it in
            continue
        delays.append(d)
        print(f"{t_fed:10.2f} {later[0]:10.2f} {d:8.2f} s")

    if not delays:
        print("\nno edges could be paired")
        return 1
    delays.sort()
    med = delays[len(delays) // 2]
    print(f"\nn={len(delays)}  min={delays[0]:.2f}s  "
          f"median={med:.2f}s  max={delays[-1]:.2f}s")
    print(f"\nArduPilot's GPS delay parameter tops out at 250 ms.")
    print("within that -- compensate with GPS1_DELAY_MS" if med <= 0.25 else
          f"median is {med / 0.25:.0f}x that ceiling -- the parameter cannot "
          "express it,\nso the pipeline has to get shorter")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("feed")
    f.add_argument("--lat", type=float, default=35.132066140)
    f.add_argument("--lon", type=float, default=139.624302130)
    f.add_argument("--height", type=float, default=75.8027)
    f.add_argument("--amp", type=float, default=5.0, help="step size, metres")
    f.add_argument("--period", type=float, default=15.0, help="seconds per edge")
    f.add_argument("--rate", type=float, default=5.0)
    f.add_argument("--seconds", type=float, default=90.0)
    f.add_argument("--events", default="/tmp/rtk-loop/lat_fed.csv")
    f.add_argument("--ramp", type=float, default=0.0,
                   help="constant speed (m/s) instead of a square wave, for "
                        "the speed check")
    f.add_argument("--ramp-dir", type=float, default=0.0,
                   help="ramp bearing in degrees (0=north, 90=east)")
    f.set_defaults(func=cmd_feed)

    v = sub.add_parser("speed")
    v.add_argument("--connect", default="127.0.0.1:5903")
    v.add_argument("--seconds", type=float, default=60.0)
    v.add_argument("--expect", type=float, default=1.0,
                   help="the speed that was fed, m/s")
    v.add_argument("--expect-course", type=float, default=0.0,
                   help="the bearing that was fed, degrees")
    v.add_argument("--skip", type=int, default=10,
                   help="RMC sentences to discard while the loop fills")
    v.set_defaults(func=cmd_speed)

    r = sub.add_parser("read")
    r.add_argument("--connect", default="127.0.0.1:5903")
    r.add_argument("--seconds", type=float, default=90.0)
    r.add_argument("--samples", default="/tmp/rtk-loop/lat_got.csv")
    r.set_defaults(func=cmd_read)

    a = sub.add_parser("analyse")
    a.add_argument("--events", default="/tmp/rtk-loop/lat_fed.csv")
    a.add_argument("--samples", default="/tmp/rtk-loop/lat_got.csv")
    a.add_argument("--max-delay", type=float, default=10.0)
    a.set_defaults(func=cmd_analyse)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
