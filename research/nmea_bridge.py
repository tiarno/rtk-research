#!/usr/bin/env python3
"""
Feed RTKLIB's NMEA solution into an autopilot as an ordinary GPS.

This is the join between the two halves of the project: RTKLIB computes a
position from a correction stream that may contain the malicious type 1033
message, emits it as standard NMEA, and the autopilot consumes it exactly as
it would any GPS receiver. Nothing in the autopilot knows RTKLIB is involved.

RTKLIB emits RMC + GGA + GSA + GSV. GGA field 6 carries fix quality
(4 = RTK fixed, 5 = RTK float), so the "quality flag does not change under
attack" property is visible to the consumer.

The NMEA is written into a pty. Point SITL at the same path:

    arducopter --serial3 uart:/tmp/ttyNMEA ...   with GPS_TYPE=5 (NMEA)

Usage:
    python3 nmea_bridge.py nmea_clean.txt --rate 5 --link /tmp/ttyNMEA
"""
import argparse
import os
import sys
import time


def groups(path):
    """Split the file into per-epoch sentence groups (each starts at RMC)."""
    out, cur = [], []
    for line in open(path, "r", errors="replace"):
        line = line.strip()
        if not line.startswith("$"):
            continue
        if line[3:6] == "RMC" and cur:
            out.append(cur)
            cur = []
        cur.append(line)
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nmea")
    ap.add_argument("--link", default="/tmp/ttyNMEA")
    ap.add_argument("--rate", type=float, default=5.0,
                    help="epoch groups per second (autopilots want >=5 Hz)")
    ap.add_argument("--loop", action="store_true",
                    help="repeat the file instead of stopping at the end")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="stop after this long (0 = until the file runs out)")
    args = ap.parse_args()

    eps = groups(args.nmea)
    if not eps:
        sys.exit(f"no NMEA sentences in {args.nmea}")

    master, slave = os.openpty()
    name = os.ttyname(slave)
    if os.path.islink(args.link) or os.path.exists(args.link):
        os.remove(args.link)
    os.symlink(name, args.link)
    print(f"pty {name} -> {args.link}")
    print(f"{len(eps)} epochs, replaying at {args.rate} Hz")
    print(f"point SITL at:  --serial3 uart:{args.link}   (GPS_TYPE=5)")
    sys.stdout.flush()

    period = 1.0 / args.rate
    t0 = time.time()
    i = sent = 0
    try:
        while True:
            if i >= len(eps):
                if not args.loop:
                    break
                i = 0
            blob = ("\r\n".join(eps[i]) + "\r\n").encode()
            try:
                os.write(master, blob)
            except OSError:
                break
            sent += 1
            i += 1
            if args.seconds and time.time() - t0 > args.seconds:
                break
            time.sleep(period)
    finally:
        print(f"sent {sent} epoch groups")
        os.close(master)
        os.close(slave)


if __name__ == "__main__":
    main()
