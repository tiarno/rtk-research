#!/usr/bin/env python3
"""
Task 2: what does an aircraft do with a quietly-corrupted RTK position?

The rest of this repo establishes that a malicious RTCM3 type 1033 message
shifts RTKLIB's reported position by ~2.4 m while its quality flag stays
unchanged. This flies that exact offset on an ArduPilot vehicle.

Method: SITL's own simulated GPS is used, so it tracks the aircraft the way a
real receiver does. The attack is applied through SIM_GPS1_GLTCH_X/Y, which
SITL adds directly to the reported latitude/longitude in degrees:

    d.latitude  += glitch_offsets.x
    d.longitude += glitch_offsets.y

That is the same thing a corrupted base-station coordinate does to an RTK
solution: the receiver reports a position offset from truth, with no change to
its fix status.

An earlier version injected GPS over MAVLink from a Python thread. That is not
used: transmitting GPS and reading telemetry over one socket from several
threads corrupts the link, the ground-truth stream stalls silently, and every
measurement after that point is worthless.

Ground truth is NOT read over MAVLink here. It comes from the dataflash log
afterwards -- see parse_sitl_log.py.

The offset flown is the one actually measured, not an invented number:

    clean  35.160876298  139.613834769  70.2814
    attack 35.160885927  139.613817453  68.7666
"""
import argparse
import math
import os
import time

from pymavlink import mavutil

D_LAT = 35.160885927 - 35.160876298
D_LON = 139.613817453 - 139.613834769
D_ALT = 68.7666 - 70.2814

HOME_LAT = 35.160876298
HOME_LON = 139.613834769
TAKEOFF_ALT = 15.0

# Waypoint for phase 3, due north of home. Kept here and in parse_sitl_log.py
# so the analysis can compare where the aircraft was TOLD to go against where
# it physically ended up.
WP_NORTH_M = 30.0
WP_LAT = HOME_LAT + WP_NORTH_M / 111320.0
WP_LON = HOME_LON


def metres(dlat, dlon, lat):
    return dlat * 111320.0, dlon * 111320.0 * math.cos(math.radians(lat))


class Vehicle:
    def __init__(self, conn):
        self.m = mavutil.mavlink_connection(conn)
        print("waiting for heartbeat...")
        self.m.wait_heartbeat()
        print(f"connected: system {self.m.target_system}")
        # Without this, EKF_STATUS_REPORT never arrives and the EKF looks
        # like it is never ready.
        self.m.mav.request_data_stream_send(
            self.m.target_system, self.m.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1)

    def set_param(self, name, value):
        self.m.mav.param_set_send(
            self.m.target_system, self.m.target_component,
            name.encode(), float(value),
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
        time.sleep(0.2)

    def mode(self, name):
        self.m.set_mode(self.m.mode_mapping()[name])
        time.sleep(1.0)

    def wait_ekf_ready(self, timeout=90):
        POS_HORIZ_ABS, CONST_POS = 16, 128
        t0, last = time.time(), None
        while time.time() - t0 < timeout:
            msg = self.m.recv_match(type="EKF_STATUS_REPORT",
                                    blocking=True, timeout=2)
            if msg is None:
                continue
            if msg.flags != last:
                print(f"  EKF flags=0x{msg.flags:04x}")
                last = msg.flags
            if (msg.flags & POS_HORIZ_ABS) and not (msg.flags & CONST_POS):
                return True
        return False

    def arm_and_takeoff(self, alt):
        self.mode("GUIDED")
        self.m.mav.command_long_send(
            self.m.target_system, self.m.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
        t0 = time.time()
        armed = False
        while time.time() - t0 < 10 and not armed:
            msg = self.m.recv_match(type=["HEARTBEAT", "STATUSTEXT"],
                                    blocking=True, timeout=1)
            if msg is None:
                continue
            if msg.get_type() == "STATUSTEXT":
                print(f"  {msg.text}")
            else:
                armed = bool(msg.base_mode &
                             mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        if not armed:
            return False
        self.m.mav.command_long_send(
            self.m.target_system, self.m.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, alt)
        t0 = time.time()
        while time.time() - t0 < 40:
            msg = self.m.recv_match(type="GLOBAL_POSITION_INT",
                                    blocking=True, timeout=2)
            if msg and msg.relative_alt / 1000.0 > alt * 0.9:
                print(f"  airborne at {msg.relative_alt/1000.0:.1f} m")
                return True
        return False

    def position(self):
        msg = self.m.recv_match(type="GLOBAL_POSITION_INT",
                                blocking=True, timeout=5)
        if msg is None:
            return None
        return msg.lat / 1e7, msg.lon / 1e7

    def goto(self, lat, lon, alt):
        self.m.mav.set_position_target_global_int_send(
            0, self.m.target_system, self.m.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000,          # position only
            int(lat * 1e7), int(lon * 1e7), alt,
            0, 0, 0, 0, 0, 0, 0, 0)

    def settle(self, secs, label, resend=None):
        """
        Hold, draining telemetry so the link does not back up.

        If `resend` is given it is called about once a second: GUIDED position
        targets expire, so a single set_position_target is not enough to make
        the vehicle actually fly the leg.
        """
        t0 = last = time.time()
        while time.time() - t0 < secs:
            self.m.recv_match(blocking=True, timeout=0.5)
            if resend and time.time() - last > 1.0:
                resend()
                last = time.time()
        print(f"  {label}: {secs:.0f}s elapsed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", default="tcp:127.0.0.1:5760")
    ap.add_argument("--hold", type=float, default=30.0)
    ap.add_argument("--attack", type=float, default=45.0)
    ap.add_argument("--goto-time", type=float, default=60.0)
    ap.add_argument("--no-glitch", action="store_true",
                    help="fly the profile but inject nothing. For the closed "
                         "loop, where the offset arrives as a malicious 1033 "
                         "in the correction stream and applying a glitch here "
                         "as well would double-count it.")
    ap.add_argument("--trigger-file", metavar="PATH",
                    help="create this file at the start of phase 2, to release "
                         "an inject_relay.py --trigger waiting on it. The "
                         "aircraft decides when the clean phase ends, so "
                         "injection cannot begin before it is holding.")
    args = ap.parse_args()

    if args.trigger_file:
        try:
            os.unlink(args.trigger_file)
        except FileNotFoundError:
            pass

    v = Vehicle(args.conn)
    v.set_param("ARMING_CHECK", 0)

    print("waiting for EKF...")
    if not v.wait_ekf_ready():
        print("EKF never became ready -- aborting")
        return 1

    print("arming + takeoff")
    if not v.arm_and_takeoff(TAKEOFF_ALT):
        print("failed to get airborne -- aborting")
        return 1

    # Hold in GUIDED, NOT LOITER. LOITER is pilot-controlled: with no RC
    # transmitter attached the throttle reads zero, so the aircraft descends
    # and disarms within a minute. An attack applied after that lands on a
    # vehicle already sitting on the ground and measures nothing.
    hold = v.position()
    if hold is None:
        print("could not read hold position -- aborting")
        return 1
    hold_lat, hold_lon = hold
    # Printed in the same shape as the `waypoint:` line below, for the same
    # reason: it is chosen at runtime, and demo_view.py needs it to pin the
    # commanded hold point on the map. Without a fixed reference marker the
    # two icons separating is unreadable -- you cannot tell which one moved.
    print(f"hold: {hold_lat:.9f},{hold_lon:.9f}")

    print(f"\nphase 1: clean GPS, holding {args.hold:.0f}s in GUIDED")
    v.goto(hold_lat, hold_lon, TAKEOFF_ALT)
    v.settle(args.hold, "clean",
             resend=lambda: v.goto(hold_lat, hold_lon, TAKEOFF_ALT))

    if args.no_glitch:
        print(f"\nphase 2: holding {args.attack:.0f}s -- no glitch applied "
              f"here; the offset arrives in the correction stream")
        if args.trigger_file:
            # Only now is the aircraft airborne, holding, and anchored to a
            # hold target captured from a clean position. Releasing the relay
            # any earlier measures a takeoff into a lying GPS instead of a
            # response to one.
            with open(args.trigger_file, "w") as f:
                f.write(f"{time.time():.3f}\n")
            print(f"  released the relay: {args.trigger_file}")
    else:
        dn, de = metres(D_LAT, D_LON, HOME_LAT)
        print(f"\nphase 2: ATTACK -- GPS glitch N={dn:+.2f} m E={de:+.2f} m "
              f"(|{math.hypot(dn, de):.2f} m| horizontal)")
        v.set_param("SIM_GPS1_GLTCH_X", D_LAT)
        v.set_param("SIM_GPS1_GLTCH_Y", D_LON)
        v.set_param("SIM_GPS1_GLTCH_Z", D_ALT)
    v.settle(args.attack, "attack",
             resend=lambda: v.goto(hold_lat, hold_lon, TAKEOFF_ALT))

    # Holding position is the least sensitive case: ArduPilot handles an EKF
    # position reset by shifting the controller target with the estimate, so a
    # step offset produces no physical movement. Navigating to a coordinate is
    # the case that matters -- the aircraft flies until it BELIEVES it is at
    # the waypoint, so a lying GPS puts it somewhere else in the real world.
    # Anchored to where the aircraft actually is, not to the module constants:
    # those are the RINEX site, and the closed loop flies wherever its base
    # station is. A waypoint 3 km away is not a miss-distance measurement.
    wp_lat = hold_lat + WP_NORTH_M / 111320.0
    wp_lon = hold_lon
    print(f"\nphase 3: navigate to a waypoint {WP_NORTH_M:.0f} m north "
          f"while the GPS is still lying")
    print(f"waypoint: {wp_lat:.9f},{wp_lon:.9f}")   # parse_sitl_log --target
    v.goto(wp_lat, wp_lon, TAKEOFF_ALT)
    v.settle(args.goto_time, "goto",
             resend=lambda: v.goto(wp_lat, wp_lon, TAKEOFF_ALT))

    print("\nland")
    v.mode("LAND")
    time.sleep(5)
    print("done -- now parse the dataflash log with parse_sitl_log.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
