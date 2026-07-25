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

Every value emitted here must be GROUND TRUTH, never an estimate. In the
closed loop these positions become the observables the vehicle's own GPS
solves, so feeding back an EKF estimate closes a positive feedback path: the
estimate defines the observables, the observables confirm the estimate, and
the channel walks away from reality with nothing to arrest it. Feeding
GLOBAL_POSITION_INT altitude did exactly that -- the solution height ran from
75.8 m to -143 m in 40 s and the aircraft never got airborne.

SIMSTATE carries truth lat/lng at 1e-7 deg but no altitude. Truth altitude
comes from SIM_STATE, which belongs to no stream group and has to be requested
by message id. If it never arrives the height is held constant -- wrong, but
stable, and the measurement lives in the horizontal channel.
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

    def request_streams():
        m.mav.request_data_stream_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL, int(args.rate * 2), 1)
        # SIM_STATE belongs to no stream group -- ArduPilot lists only the
        # ArduPilot-specific SIMSTATE, in EXTRA1 -- so requesting the streams
        # is not enough and it has to be asked for by message id. Without it
        # the only altitude available is the vehicle's own estimate, which
        # cannot be fed back into the observables. See the module docstring.
        m.mav.command_long_send(
            m.target_system, m.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            mavutil.mavlink.MAVLINK_MSG_ID_SIM_STATE,
            1e6 / args.rate, 0, 0, 0, 0, 0)

    request_streams()
    print(f"connected, streaming truth at {args.rate} Hz", file=sys.stderr)

    lat = lon = None
    alt = args.alt
    period = 1.0 / args.rate
    t0 = last = time.time()
    sent = 0
    last_req = t0
    truth_alt = False       # SIM_STATE seen: altitude is ground truth
    warned = False

    while True:
        msg = m.recv_match(blocking=True, timeout=0.5)
        if msg is not None:
            t = msg.get_type()
            if t == "SIMSTATE":
                lat, lon = msg.lat / 1e7, msg.lng / 1e7
            elif t == "SIM_STATE":
                alt = msg.alt
                if not truth_alt:
                    print("truth altitude from SIM_STATE", file=sys.stderr)
                    truth_alt = True
        now = time.time()
        if not truth_alt and not warned and now - t0 > 10.0:
            # Deliberately NOT falling back to GLOBAL_POSITION_INT: that is
            # the vehicle's own estimate, and feeding it back is what makes
            # the vertical channel diverge. A constant is wrong but stable,
            # and the measurement lives in the horizontal channel anyway.
            print(f"WARNING: no SIM_STATE after 10s -- holding height at "
                  f"{args.alt:.1f} m", file=sys.stderr)
            warned = True
        # Stream rates can lapse; re-requesting keeps the truth flowing.
        if now - last_req > 5.0:
            request_streams()
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
