#!/usr/bin/env python3
"""
Feed RTCM3 streams into pseudo-terminals so RTKLIB receives them over a UART.

This stands in for the serial link between a UHF/VHF correction radio and a
rover's receiver. RTKLIB's decoder never learns its transport -- strread()
demuxes by stream type into one buffer and every type lands in the same
input_rtcm3() -- so proving the attack over a real tty closes the gap between
"delivered from a file" and "delivered over the air" without transmitting.

Creates two ptys, symlinks them to predictable paths, and paces the bytes
using the .tag files written by rnx2rtcm3 so rover and base stay aligned.

RTKLIB builds its device path as sprintf(dev,"/dev/%s",port), so a pty linked
at /tmp/ttyX is addressed as "../tmp/ttyX".

Usage:
    python serial_feed.py rover.rtcm3 base.rtcm3 --speed 500
"""
import argparse
import os
import struct
import sys
import time


def read_tags(path):
    """Return [(tick_ms, fpos)] from a .tag file, or [] if absent."""
    try:
        with open(path, "rb") as fh:
            fh.read(64 + 4 + 8)          # header + tick_f + time
            body = fh.read()
    except FileNotFoundError:
        return []
    return [struct.unpack("<II", body[i:i + 8])
            for i in range(0, len(body) - 7, 8)]


def make_pty(link):
    master, slave = os.openpty()
    name = os.ttyname(slave)
    if os.path.islink(link) or os.path.exists(link):
        os.remove(link)
    os.symlink(name, link)
    return master, slave, name


def write_paced(fd, data, chunk=256):
    """Write in small chunks so the pty buffer cannot deadlock the feeder."""
    for i in range(0, len(data), chunk):
        os.write(fd, data[i:i + chunk])
        time.sleep(0.002)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rover")
    ap.add_argument("base")
    ap.add_argument("--speed", type=float, default=500.0,
                    help="replay speed multiplier (default 500)")
    ap.add_argument("--rover-link", default="/tmp/ttyRover")
    ap.add_argument("--base-link", default="/tmp/ttyBase")
    ap.add_argument("--settle", type=float, default=1.5,
                    help="seconds to wait for the reader to open the ptys")
    args = ap.parse_args()

    rov = open(args.rover, "rb").read()
    bas = open(args.base, "rb").read()
    rtags = read_tags(args.rover + ".tag")
    btags = read_tags(args.base + ".tag")
    if not rtags or not btags:
        sys.exit("need .tag files next to both streams (rnx2rtcm3 writes them)")

    mrov, srov, nrov = make_pty(args.rover_link)
    mbas, sbas, nbas = make_pty(args.base_link)
    print(f"rover pty {nrov} -> {args.rover_link}")
    print(f"base  pty {nbas} -> {args.base_link}")
    print(f"RTKLIB paths: ../tmp/{os.path.basename(args.rover_link)} "
          f"../tmp/{os.path.basename(args.base_link)}")
    sys.stdout.flush()

    time.sleep(args.settle)

    # Merge both epoch schedules and emit in tick order.
    events = ([(t, "r", p) for t, p in rtags] + [(t, "b", p) for t, p in btags])
    events.sort(key=lambda e: e[0])

    prev = {"r": 0, "b": 0}
    t0 = time.time()
    sent = {"r": 0, "b": 0}
    for tick, which, fpos in events:
        target = t0 + (tick / 1000.0) / args.speed
        delay = target - time.time()
        if delay > 0:
            time.sleep(delay)
        buf, fd = (rov, mrov) if which == "r" else (bas, mbas)
        chunk = buf[prev[which]:fpos]
        if chunk:
            write_paced(fd, chunk)
            sent[which] += len(chunk)
        prev[which] = fpos

    print(f"fed rover={sent['r']} bytes, base={sent['b']} bytes")
    time.sleep(1.0)
    for fd in (mrov, srov, mbas, sbas):
        os.close(fd)


if __name__ == "__main__":
    main()
