#!/usr/bin/env python3
"""
Side-by-side replay: the same packet against two builds of the same decoder.

    ./demo_split.py --left silent.jsonl --right abort.jsonl
    # serves http://<host>:8081

Both inputs are --record files from demo_view.py (one per loop_demo.sh run).
Nothing here collects; it only replays, so it can never be mistaken for, or
interfere with, a live chain. The page says "recorded" on screen for the same
reason: the split view only exists as a replay, and the talk should say so.

ALIGNMENT. The two runs start at different wall-clock moments and take
different times to reach the air, so playing both from their own t=0 puts the
packet at different moments on the two sides -- which is the one moment the
screen exists to show. Each run is anchored on its FIRST frame with
phase == "attack" -- the moment the flight driver releases the relay -- and
both play on one clock measured from that anchor: T-30 s ... packet ... T+N s.
A run that never reaches phase 2 is refused rather than guessed at.

Why not the first frame with injected > 0, which sounds more precise: in a
fortified run RTKLIB aborts on the first spliced 1033, the relay's last count
goes out only in its "client gone" line, which demo_view.py does not parse, so
`injected` stays 0 for the whole recording. Measured 2026-11-16: in the
unfortified recording the first injection lands 0.2 s after phase 2 begins;
in the fortified one the last NMEA sentence is 0.3 s BEFORE it (phase comes
from tailing flight.log, which trails the relay release slightly). So the
"packet" line is good to about half a second on both sides.

One thread, one clock. Two independent replays (two demo_view.py --replay
processes) drift apart and start whenever each browser connects; this emits a
single combined frame {T, L, R} at 10 Hz so the two sides cannot disagree
about time.
"""
import argparse
import json
import os
import sys
import threading
import time

from demo_view import Hub, make_handler   # same SSE server as the single view


def load(path):
    with open(path) as fh:
        frames = [json.loads(line) for line in fh if line.strip()]
    if not frames:
        sys.exit(f"{path}: no frames")
    anchor = next((f["t"] for f in frames if f.get("phase") == "attack"), None)
    if anchor is None:
        sys.exit(f"{path}: never reaches phase 2 (attack) -- nothing to "
                 "align on")
    # Ground level: truth altitude on the pad. Not the first truth frame --
    # that can predate SITL setting home and read 0.0 (it does in the August
    # recording); the first frame that also has a GPS fix is after home is set
    # and before takeoff.
    ground = next((f["truth"]["h"] for f in frames
                   if f.get("truth") and f.get("gps")), None)
    return {"path": path, "frames": frames, "anchor": anchor, "ground": ground}


def sample(run, T):
    """Latest frame at or before anchor+T (binary search), or None before it."""
    fr, want = run["frames"], run["anchor"] + T
    lo, hi = 0, len(fr)
    while lo < hi:
        mid = (lo + hi) // 2
        if fr[mid]["t"] <= want:
            lo = mid + 1
        else:
            hi = mid
    return fr[lo - 1] if lo else None


def pump(left, right, hub, stop, lead, tail, rate, speed):
    end = max(left["frames"][-1]["t"] - left["anchor"],
              right["frames"][-1]["t"] - right["anchor"])
    if tail is not None:
        end = min(end, tail)
    start = -lead
    period = 1.0 / rate
    while not stop.is_set():
        t0 = time.monotonic()
        T = start
        while T <= end and not stop.is_set():
            hub.publish({
                "T": round(T, 2), "start": start, "end": end,
                "L": sample(left, T), "R": sample(right, T),
            })
            T += period * speed
            due = t0 + (T - start) / speed
            stop.wait(max(0.0, due - time.monotonic()))
        stop.wait(3.0)          # hold the final frame, then loop


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--left", required=True, metavar="JSONL")
    ap.add_argument("--right", required=True, metavar="JSONL")
    ap.add_argument("--left-label", default="Unfortified build")
    ap.add_argument("--left-sub", default="no _FORTIFY_SOURCE: the coordinate "
                    "is zeroed silently")
    ap.add_argument("--right-label", default="Fortified build")
    ap.add_argument("--right-sub", default="_FORTIFY_SOURCE=2: strncpy "
                    "overflow detected, process aborts")
    ap.add_argument("--lead", type=float, default=30.0,
                    help="seconds of clean hold shown before the packet")
    ap.add_argument("--tail", type=float, default=None,
                    help="stop this many seconds after the packet "
                         "(default: end of the longer run)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--page", default=os.path.join(here, "demo_split.html"))
    args = ap.parse_args()

    left, right = load(args.left), load(args.right)
    for side, run in (("left", left), ("right", right)):
        print(f"{side}: {run['path']}  packet at t={run['anchor']:.1f} s, "
              f"{len(run['frames'])} frames, ground {run['ground']}")

    meta = {
        "L": {"label": args.left_label, "sub": args.left_sub,
              "ground": left["ground"]},
        "R": {"label": args.right_label, "sub": args.right_sub,
              "ground": right["ground"]},
    }

    def page():
        with open(args.page, encoding="utf-8") as fh:
            return fh.read().replace("/*__META__*/null", json.dumps(meta))

    hub, stop = Hub(), threading.Event()
    threading.Thread(target=pump, daemon=True,
                     args=(left, right, hub, stop, args.lead, args.tail,
                           args.rate, args.speed)).start()

    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer((args.bind, args.port), make_handler(hub, page))
    srv.daemon_threads = True
    print(f"split view on http://localhost:{args.port}/   (ctrl-c to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
