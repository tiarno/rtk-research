#!/usr/bin/env python3
"""
Stream a simulated vehicle's true position, for gnss_sim to observe.

Emits "lat,lon,height" lines on stdout at a fixed rate, read from SITL's
ground truth. Pipe it into `gnss_sim --live`, which turns each line into one
epoch of GNSS observables:

    mav_pos.py | gnss_sim nav.rnx <base_ecef> --live :5901 :5902

This only ever READS from the MAVLink connection. An earlier version of this
harness both transmitted GPS and read telemetry over one socket from several
threads; that corrupts the link and the ground-truth stream stalls silently,
which is indistinguishable from a vehicle holding perfectly still.

SIMSTATE carries lat/lng but no altitude, so height comes from
GLOBAL_POSITION_INT when available and falls back to --alt otherwise. The
horizontal channel is the one the measurement depends on.
"""
import argparse
import sys
import time

from pymavlink import mavutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", default="tcp:127.0.0.1:5760")
    ap.add_argument("--rate", type=float, default=5.0)
    ap.add_argument("--alt", type=float, default=70.0,
                    help="fallback ellipsoidal height (m)")
    ap.add_argument("--seconds", type=float, default=0.0)
    args = ap.parse_args()

    m = mavutil.mavlink_connection(args.conn)
    print("waiting for heartbeat...", file=sys.stderr)
    m.wait_heartbeat()
    m.mav.request_data_stream_send(
        m.target_system, m.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL, int(args.rate * 2), 1)
    print(f"connected, streaming truth at {args.rate} Hz", file=sys.stderr)

    lat = lon = None
    alt = args.alt
    period = 1.0 / args.rate
    t0 = last = time.time()
    sent = 0
    last_req = t0

    while True:
        msg = m.recv_match(blocking=True, timeout=0.5)
        if msg is not None:
            t = msg.get_type()
            if t == "SIMSTATE":
                lat, lon = msg.lat / 1e7, msg.lng / 1e7
            elif t == "GLOBAL_POSITION_INT":
                alt = msg.alt / 1000.0

        now = time.time()
        # Stream rates can lapse; re-requesting keeps SIMSTATE flowing.
        if now - last_req > 5.0:
            m.mav.request_data_stream_send(
                m.target_system, m.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL, int(args.rate * 2), 1)
            last_req = now

        if lat is not None and now - last >= period:
            print(f"{lat:.9f},{lon:.9f},{alt:.4f}", flush=True)
            last = now
            sent += 1
            if sent % 50 == 0:
                print(f"  {sent} positions sent", file=sys.stderr)

        if args.seconds and now - t0 > args.seconds:
            break

    print(f"sent {sent} positions", file=sys.stderr)


if __name__ == "__main__":
    main()
