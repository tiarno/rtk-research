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

    feed    : emit "lat,lon,height" at <rate> Hz, stepping latitude periodically
    read    : connect to RTKLIB's NMEA server and timestamp every GGA
    analyse : pair the edges from both logs and report the delay

Driven by loop_latency.sh.
"""
import argparse
import math
import socket
import sys
import time

M_PER_DEG = 111320.0


def cmd_feed(args):
    """Square wave in latitude, one edge every --period seconds."""
    events = open(args.events, "w", buffering=1)
    events.write("unix,lat\n")
    lat0, lon, hgt = args.lat, args.lon, args.height
    period = 1.0 / args.rate
    high = False
    t0 = last_edge = time.time()
    next_tick = t0

    while True:
        now = time.time()
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
    f.set_defaults(func=cmd_feed)

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
