#!/usr/bin/env python3
"""Measure the forced-landing attack from an ArduPilot dataflash log.

On a fortified build the malicious 1033 does not corrupt the position -- it
kills the process. The aircraft loses GPS, declares an EKF failsafe and lands
itself. That is a *second attack*, not a mitigation: the attacker chooses the
moment, so they choose roughly where the aircraft comes down.

"Roughly" is the whole question, and it is what this measures. With no position
estimate the descent has no horizontal hold, so the aircraft slides while it
comes down. The dispersion between the point of GPS loss and the point of
touchdown is the attacker's targeting error.

    ./land_drift.py /tmp/rtk-loop/logs/00000022.BIN

Prints "no EKF failsafe" and exits 1 on a control run, so it cannot silently
report a forced landing that never happened.
"""
import math
import sys
from pymavlink import mavutil

# ArduPilot Copter LogErrorSubsystem
SUBSYS_FAILSAFE_EKFINAV = 17
MODE_LAND = 9


def hdist(a, b):
    """Metres between two (lat, lon) pairs. Flat-earth; distances here are
    tens of metres, where the error is far below the measurement noise."""
    r = 6378137.0
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    mlat = math.radians((a[0] + b[0]) / 2)
    return math.hypot(dlat * r, dlon * r * math.cos(mlat))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    m = mavutil.mavlink_connection(path)

    sim = []            # (t, lat, lon, alt) ground truth
    gps_loss = None     # first GPS Status -> 0
    failsafe = None     # EKF nav failsafe
    land_mode = None    # mode change to LAND
    touchdown = None    # SIM reports ground contact
    disarm = None
    gps_status_prev = None

    while True:
        r = m.recv_match(type=['SIM', 'GPS', 'ERR', 'MODE', 'MSG'])
        if r is None:
            break
        t = getattr(r, 'TimeUS', 0) / 1e6
        ty = r.get_type()
        if ty == 'SIM':
            sim.append((t, r.Lat, r.Lng, r.Alt))
        elif ty == 'GPS':
            if gps_status_prev is not None and r.Status == 0 and gps_status_prev != 0:
                if gps_loss is None:
                    gps_loss = t
            gps_status_prev = r.Status
        elif ty == 'ERR':
            if r.Subsys == SUBSYS_FAILSAFE_EKFINAV and r.ECode != 0 and failsafe is None:
                failsafe = t
        elif ty == 'MODE':
            if r.Mode == MODE_LAND and land_mode is None:
                land_mode = t
        elif ty == 'MSG':
            if 'Hit ground' in r.Message and touchdown is None:
                touchdown = t
            elif 'Disarming' in r.Message and disarm is None:
                disarm = t

    if not sim:
        print(f"{path}: no SIM (ground truth) records -- not a SITL log?")
        return 2
    if failsafe is None:
        print(f"=== {path} ===")
        print("no EKF failsafe in this log -- the aircraft was never forced down.")
        print("This is what a control run looks like. Nothing to measure.")
        return 1
    if gps_loss is None:
        print(f"{path}: EKF failsafe present but GPS never dropped to Status=0;")
        print("something other than the attack triggered it. Not reporting a number.")
        return 1

    if touchdown is None:
        touchdown = disarm if disarm is not None else sim[-1][0]

    def at(t):
        return min(sim, key=lambda s: abs(s[0] - t))

    p_loss, p_fs, p_gnd = at(gps_loss), at(failsafe), at(touchdown)
    ll_loss = (p_loss[1], p_loss[2])
    ll_fs = (p_fs[1], p_fs[2])
    ll_gnd = (p_gnd[1], p_gnd[2])

    agl = p_fs[3] - p_gnd[3]
    descent = touchdown - failsafe
    seg = [s for s in sim if failsafe <= s[0] <= touchdown]
    mx_t, mx_d = failsafe, 0.0
    for s in seg:
        d = hdist(ll_fs, (s[1], s[2]))
        if d > mx_d:
            mx_d, mx_t = d, s[0]

    print(f"=== forced-landing profile: {path} ===")
    print()
    print(f"  GPS lost        t={gps_loss:7.1f} s   (Status -> 0)")
    print(f"  EKF failsafe    t={failsafe:7.1f} s   (+{failsafe - gps_loss:.1f} s)")
    if land_mode is not None:
        print(f"  MODE -> LAND    t={land_mode:7.1f} s")
    print(f"  touchdown       t={touchdown:7.1f} s   "
          f"(+{touchdown - gps_loss:.1f} s from GPS loss)")
    print()
    print(f"  altitude at failsafe        {agl:7.2f} m AGL")
    print(f"  descent time                {descent:7.1f} s")
    if descent > 0:
        print(f"  mean descent rate           {agl / descent:7.2f} m/s")
    print()
    print("  horizontal dispersion -- the attacker's targeting error:")
    print(f"    GPS loss  -> touchdown    {hdist(ll_loss, ll_gnd):7.2f} m")
    print(f"    failsafe  -> touchdown    {hdist(ll_fs, ll_gnd):7.2f} m")
    print(f"    max excursion             {mx_d:7.2f} m at t={mx_t:.1f} s")
    print()
    print("  NOTE: SITL default is zero wind. This dispersion is a FLOOR, not")
    print("  an expected value. Wind, a higher hover, or a vehicle with more")
    print("  residual velocity at failsafe all increase it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
