#!/usr/bin/env python3
"""
Live view for the packet-to-propeller demo: where the aircraft actually is,
where its GPS says it is, and the RTK quality flag that never changes.

    ./demo_view.py                        # live; serves http://<host>:8080
    ./demo_view.py --replay run.jsonl     # same renderer, recorded run

Two processes' worth of work, deliberately split into collector and renderer.
The collector owns every socket and emits one state frame at 10 Hz; the
renderer only ever consumes frames. That buys two things. The renderer cannot
stall the NMEA read (see below for why that matters), and every live run is
recorded to JSONL as a side effect, so `--replay` gives the fallback demo for
free -- identical pixels, no video, and rehearsable without booting SITL.

EVERYTHING HERE IS A PASSIVE OBSERVER. Nothing it does can alter a
measurement, and that is a property worth being able to defend on stage:

  * The GPS-claimed position and the fix quality come off :5903 as a SECOND
    client of RTKLIB's own NMEA server. stream.c gives tcpsvr MAXCLI=32 client
    slots and writetcpsvr() fans every write out to all of them, so this sees
    the exact bytes the flight controller is being fed, not a re-derivation.

    One hazard follows from that code. send_nb() returns -1 on a SHORT write,
    and writetcpsvr() responds by calling discontcp() on that client. So a
    viewer that stops reading fast enough is dropped silently -- the map would
    freeze mid-talk while the aircraft kept flying. Hence: the socket read is
    its own thread that does nothing but buffer and parse, and it reconnects.
    The autopilot is unaffected either way; the failure is per-client.

  * Truth comes from a THIRD MAVLink endpoint on SITL (SERIAL2, :5763).
    Separate endpoint, not a shared one -- mav_pos.py's docstring records what
    sharing one socket between two consumers costs.

  * Everything else is read from files the chain already writes.

DO NOT PUT HDOP ON SCREEN. outnmea_gga() declares `double dop=1.0` and never
assigns to it, so an unchanging HDOP is a property of RTKLIB's writer and not
evidence about the attack. Satellite count (sol.ns) and correction age are
real values and are safe to show.
"""
import argparse
import json
import math
import os
import queue
import socket
import sys
import threading
import time

# Same convention as parse_sitl_log.py and sign_check.py, so a number read off
# the screen matches the one the post-hoc parser prints for the same run.
M_PER_DEG = 111320.0

# GGA quality indicator. nmea_solq[] in solution.c maps SOLQ_FIX -> 4, so this
# is genuinely "RTK fixed", read off the wire rather than asserted.
GGA_FIX = 4
GGA_QUALITY = {
    0: ("NO FIX", "bad"),
    1: ("SINGLE", "warn"),
    2: ("DGPS", "warn"),
    3: ("PPS", "warn"),
    4: ("RTK FIXED", "good"),
    5: ("RTK FLOAT", "warn"),
    6: ("DEAD RECKONING", "bad"),
}


# ---------------------------------------------------------------- shared state

class State:
    """Latest value of everything, with the wall time it arrived."""

    def __init__(self):
        self.lock = threading.Lock()
        self.t0 = time.monotonic()
        self.d = {
            "gps": None,        # {lat, lon, h, q, ns, age}
            "gps_at": 0.0,
            "truth": None,      # {lat, lon, h}
            "truth_at": 0.0,
            "hold": None,       # {lat, lon}  commanded hold point
            "wp": None,         # {lat, lon}  commanded waypoint
            "base": None,       # {x, y, z}   what RTKLIB adopted
            "base0": None,      # {x, y, z}   what it adopted first (the truth)
            "armed": False,     # relay injecting
            "injected": 0,
            "frames": 0,      # -1 on the control path: no splicer, none counted
            "relayed": 0,     # bytes, the figure that exists on both paths
            "phase": "startup",
            "notes": [],        # recent status text, newest last
        }

    def now(self):
        return time.monotonic() - self.t0

    def set(self, **kw):
        with self.lock:
            self.d.update(kw)

    def note(self, text):
        with self.lock:
            notes = self.d["notes"]
            if not notes or notes[-1] != text:
                notes.append(text)
                del notes[:-6]

    def frame(self):
        with self.lock:
            f = dict(self.d)
            f["notes"] = list(f["notes"])
        t = self.now()
        f["t"] = round(t, 2)
        # Age of each live source, so the renderer can grey out a dead feed
        # instead of showing a stale position as if it were current.
        f["gps_age"] = round(t - f.pop("gps_at"), 2) if f["gps"] else None
        f["truth_age"] = round(t - f.pop("truth_at"), 2) if f["truth"] else None
        return f


# ------------------------------------------------------------------ NMEA (GPS)

def nmea_checksum_ok(line):
    if "*" not in line:
        return False
    body, _, sm = line[1:].partition("*")
    try:
        want = int(sm[:2], 16)
    except ValueError:
        return False
    got = 0
    for ch in body:
        got ^= ord(ch)
    return got == want


def dm2deg(field, hemi):
    """ddmm.mmmm / dddmm.mmmm -> signed degrees."""
    if not field:
        return None
    dot = field.find(".")
    deg = float(field[:dot - 2])
    minutes = float(field[dot - 2:])
    val = deg + minutes / 60.0
    return -val if hemi in ("S", "W") else val


def parse_gga(line):
    f = line.split(",")
    if len(f) < 15:
        return None
    try:
        lat = dm2deg(f[2], f[3])
        lon = dm2deg(f[4], f[5])
        q = int(f[6]) if f[6] else 0
        ns = int(f[7]) if f[7] else 0
        alt = float(f[9]) if f[9] else 0.0
        geoid = float(f[11]) if f[11] else 0.0
        age = float(f[13]) if f[13] else 0.0
    except ValueError:
        return None
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon, "h": alt + geoid, "q": q, "ns": ns,
            "age": age}


def nmea_reader(st, host, port, stop):
    """
    Second client on RTKLIB's NMEA server. Buffers, parses, reconnects.

    Deliberately does no work beyond parsing: if this thread falls behind, the
    socket send buffer fills, send_nb() short-writes, and writetcpsvr() drops
    us without a word. Rendering happens somewhere else entirely.
    """
    buf = b""
    while not stop.is_set():
        s = None
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.settimeout(1.0)
            st.note(f"NMEA connected {host}:{port}")
            while not stop.is_set():
                try:
                    data = s.recv(8192)
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                # Cap the backlog: if we ever do fall behind, drop old bytes
                # rather than grow without bound and fall further behind.
                if len(buf) > 65536:
                    buf = buf[-8192:]
                while b"\n" in buf:
                    raw, _, buf = buf.partition(b"\n")
                    line = raw.decode("ascii", "replace").strip()
                    # Partial writes leave holes, so every sentence is
                    # checksum-validated and a bad one is simply dropped.
                    if not line.startswith("$") or not nmea_checksum_ok(line):
                        continue
                    if line[3:6] == "GGA":
                        g = parse_gga(line)
                        if g:
                            st.set(gps=g, gps_at=st.now())
            st.note("NMEA disconnected")
        except OSError:
            pass
        finally:
            if s:
                try:
                    s.close()
                except OSError:
                    pass
        buf = b""
        stop.wait(1.0)


# ---------------------------------------------------------------- truth (SITL)

def truth_reader(st, conn, stop):
    """
    Ground truth from SITL's third MAVLink endpoint.

    SIMSTATE carries truth lat/lng; SIM_STATE carries truth altitude and
    belongs to no stream group, so it is requested by message id -- the same
    dance mav_pos.py documents. Read-only: this never transmits anything but
    stream requests.
    """
    try:
        from pymavlink import mavutil
    except ImportError:
        st.note("pymavlink missing -- no truth feed")
        return

    while not stop.is_set():
        try:
            m = mavutil.mavlink_connection(conn)
            st.note(f"truth: waiting for heartbeat on {conn}")
            m.wait_heartbeat()
            st.note("truth: connected")

            def request():
                m.mav.request_data_stream_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1)
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                    mavutil.mavlink.MAVLINK_MSG_ID_SIM_STATE,
                    1e5, 0, 0, 0, 0, 0)

            request()
            last_req = time.time()
            lat = lon = None
            alt = 0.0
            while not stop.is_set():
                msg = m.recv_match(blocking=True, timeout=0.5)
                if msg is not None:
                    t = msg.get_type()
                    if t == "SIMSTATE":
                        lat, lon = msg.lat / 1e7, msg.lng / 1e7
                        if lat is not None:
                            st.set(truth={"lat": lat, "lon": lon, "h": alt},
                                   truth_at=st.now())
                    elif t == "SIM_STATE":
                        alt = msg.alt
                if time.time() - last_req > 5.0:
                    request()
                    last_req = time.time()
        except Exception as e:            # noqa: BLE001 - a demo must retry
            st.note(f"truth: {type(e).__name__}")
        stop.wait(2.0)


# ------------------------------------------------------------------- log tails

def tail(path, stop, on_line, on_reset=None, poll=0.25):
    """
    Follow a file that may not exist yet and may be truncated by a re-run.

    Starts from the beginning of the file, so a viewer launched mid-run still
    picks up the hold point and waypoint -- each printed once and never
    repeated. loop_demo.sh truncates these logs before anything else starts so
    that "the beginning" cannot mean the previous run.

    on_reset fires when the file is truncated or replaced, i.e. a new run has
    begun. Everything derived from this file must be cleared there: a phase or
    an armed flag carried over from the last run is a screen that claims an
    attack is under way when none is.
    """
    f = None
    inode = None
    while not stop.is_set():
        try:
            if f is None:
                f = open(path, "r", errors="replace")
                inode = os.fstat(f.fileno()).st_ino
            line = f.readline()
            if line:
                on_line(line.rstrip("\n"))
                continue
            # No new data: check whether the file was replaced or truncated.
            try:
                sr = os.stat(path)
                if sr.st_ino != inode or sr.st_size < f.tell():
                    f.close()
                    f = None
                    if on_reset:
                        on_reset()
                    continue
            except OSError:
                f.close()
                f = None
        except OSError:
            if f:
                try:
                    f.close()
                except OSError:
                    pass
            f = None
        stop.wait(poll)


def watch_flight(st, path, stop):
    """Phases, plus the hold point and waypoint chosen at runtime."""
    def on_line(line):
        s = line.strip()
        if s.startswith("hold: "):
            try:
                lat, lon = (float(x) for x in s[6:].split(","))
                st.set(hold={"lat": lat, "lon": lon})
            except ValueError:
                pass
        elif s.startswith("waypoint: "):
            try:
                lat, lon = (float(x) for x in s[10:].split(","))
                st.set(wp={"lat": lat, "lon": lon})
            except ValueError:
                pass
        elif s.startswith("phase 1"):
            st.set(phase="clean")
            st.note("phase 1: clean GPS, holding")
        elif s.startswith("phase 2"):
            st.set(phase="attack")
            st.note("phase 2: correction stream compromised")
        elif s.startswith("phase 3"):
            st.set(phase="goto")
            st.note("phase 3: navigating to waypoint")
        elif s == "land":
            st.set(phase="land")
        elif s.startswith("airborne at"):
            st.note(s)

    def on_reset():
        st.set(phase="startup", hold=None, wp=None)

    tail(path, stop, on_line, on_reset)


def watch_relay(st, path, stop):
    """Injection count, and the moment the relay arms."""
    def on_line(line):
        s = line.strip()
        if s.startswith("status: "):
            kv = {}
            for tok in s[8:].split():
                k, _, v = tok.partition("=")
                try:
                    kv[k] = int(v)
                except ValueError:
                    pass
            st.set(injected=kv.get("injected", 0), frames=kv.get("frames", 0),
                   relayed=kv.get("bytes", 0))
        elif "ATTACK" in s:
            st.set(armed=True)
            st.note("relay armed: one extra 1033 after every 1005")

    def on_reset():
        st.set(armed=False, injected=0, frames=0, relayed=0)

    tail(path, stop, on_line, on_reset)


def watch_rtklib(st, path, stop):
    """
    The base coordinate RTKLIB actually adopted.

    e2e_harness.c prints a line only when rtk.rb changes, which is precisely
    when sta.pos gets overwritten -- so this is the cause, on screen, next to
    an unchanged fix indicator. The harness sets line buffering for exactly
    this reason; without it the line sits in a 4 KB stdio buffer for minutes.

    Line shape:  HH:MM:SS.S  Q  lat  lon  height  rbX rbY rbZ  v=...
    """
    def on_line(line):
        f = line.split()
        if len(f) < 8 or ":" not in f[0]:
            return
        try:
            base = {"x": float(f[5]), "y": float(f[6]), "z": float(f[7])}
        except ValueError:
            return
        with st.lock:
            first = st.d["base0"] is None
        st.set(base=base)
        if first:
            st.set(base0=base)

    def on_reset():
        st.set(base=None, base0=None)

    tail(path, stop, on_line, on_reset)


def watch_trigger(st, path, stop):
    """
    Trigger file existence: the flight driver releasing the relay.

    Tracks it in both directions rather than latching on first sight.
    loop_demo.sh removes the trigger at startup, so a latched flag would carry
    the previous run's armed state into a run that has not armed anything.
    """
    seen = None
    while not stop.is_set():
        now = os.path.exists(path)
        if now != seen:
            st.set(armed=now)
            seen = now
        stop.wait(0.2)


# ------------------------------------------------------------------ frame pump

class Hub:
    """Fan state frames out to every connected browser."""

    def __init__(self):
        self.lock = threading.Lock()
        self.subs = []
        self.last = None

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.subs.append(q)
            if self.last is not None:
                q.put_nowait(self.last)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, frame):
        payload = json.dumps(frame, separators=(",", ":"))
        with self.lock:
            self.last = payload
            for q in list(self.subs):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    # A browser that cannot keep up gets dropped rather than
                    # backing pressure up into the collector.
                    self.subs.remove(q)


def open_record(path):
    """
    Open the frame recording, or return None and say why.

    Never fatal. Losing the recording costs the fallback demo; letting this
    raise costs the live view, because it runs on the thread that publishes
    frames -- the page would load, connect, and then silently never update.

    Deliberately does NOT create the directory. The chain makes the scratch
    directory itself, so a missing one means the path is wrong -- and creating
    it converts a loud, correct failure into a quiet one: frames get recorded
    into a plausible-looking directory that no log will ever appear in. That
    happened on the first Windows run here.
    """
    if not path:
        return None
    try:
        return open(path, "w", buffering=1)
    except OSError as e:
        print(f"WARNING: not recording frames to {path}: {e}", file=sys.stderr)
        print("  The live view is unaffected, but there will be no "
              "--replay file for this run.", file=sys.stderr)
        return None


def pump_live(st, hub, stop, rate, record):
    period = 1.0 / rate
    out = open_record(record)
    try:
        nxt = time.monotonic()
        while not stop.is_set():
            frame = st.frame()
            hub.publish(frame)
            if out:
                out.write(json.dumps(frame, separators=(",", ":")) + "\n")
            nxt += period
            delay = nxt - time.monotonic()
            if delay < 0:
                nxt = time.monotonic()
                delay = 0
            stop.wait(delay)
    finally:
        if out:
            out.close()


def pump_replay(path, hub, stop, speed):
    """
    Replay recorded frames at their original cadence.

    The renderer cannot tell the difference, which is the point: the fallback
    demo is the real demo, played back. Loops, so it can be left running.
    """
    with open(path) as fh:
        frames = [json.loads(line) for line in fh if line.strip()]
    if not frames:
        print(f"{path}: no frames", file=sys.stderr)
        return
    while not stop.is_set():
        t_wall = time.monotonic()
        t_frame = frames[0].get("t", 0.0)
        for fr in frames:
            if stop.is_set():
                return
            due = t_wall + (fr.get("t", 0.0) - t_frame) / speed
            delay = due - time.monotonic()
            if delay > 0:
                stop.wait(delay)
            hub.publish(fr)
        stop.wait(2.0)


# ---------------------------------------------------------------------- server

def make_handler(hub, page):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass                      # the console belongs to the demo

        def _head(self, ctype, length=None, stream=False):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            if stream:
                self.send_header("Connection", "keep-alive")
                self.send_header("Transfer-Encoding", "chunked")
            elif length is not None:
                self.send_header("Content-Length", str(length))
            self.end_headers()

        def do_GET(self):
            if self.path.startswith("/stream"):
                self.serve_stream()
            elif self.path in ("/", "/index.html"):
                body = page().encode("utf-8")
                self._head("text/html; charset=utf-8", len(body))
                self.wfile.write(body)
            else:
                self.send_error(404)

        def serve_stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            q = hub.subscribe()
            try:
                while True:
                    try:
                        payload = q.get(timeout=5.0)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(b"data: " + payload.encode() + b"\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    return Handler


# ------------------------------------------------------------------------ main

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", metavar="JSONL",
                    help="replay a recorded run instead of collecting")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="replay speed multiplier")
    ap.add_argument("--nmea", default="127.0.0.1:5903",
                    help="RTKLIB NMEA server to observe")
    ap.add_argument("--truth", default="tcp:127.0.0.1:5763",
                    help="SITL MAVLink endpoint carrying ground truth")
    ap.add_argument("--scratch", default=os.environ.get("T", "/tmp/rtk-loop"),
                    help="directory holding the chain's logs")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--bind", default="0.0.0.0",
                    help="0.0.0.0 so a browser on the Windows side of WSL "
                         "can reach it")
    ap.add_argument("--rate", type=float, default=10.0,
                    help="state frames per second")
    ap.add_argument("--record", metavar="JSONL",
                    help="write frames here (default <scratch>/view.jsonl)")
    ap.add_argument("--page", default=os.path.join(here, "demo_view.html"))
    args = ap.parse_args()

    hub = Hub()
    stop = threading.Event()

    def page():
        # Re-read per request so the renderer can be edited and reloaded
        # without restarting a collector that is mid-flight.
        with open(args.page, encoding="utf-8") as fh:
            return fh.read()

    threads = []
    if args.replay:
        threads.append(threading.Thread(
            target=pump_replay, args=(args.replay, hub, stop, args.speed),
            daemon=True))
        print(f"replaying {args.replay} at {args.speed}x")
    else:
        st = State()
        host, _, port = args.nmea.rpartition(":")
        T = args.scratch
        # Say so loudly. If the scratch path is wrong the log tails simply
        # never find a file, and the result is a screen that looks alive --
        # position and fix quality arrive over TCP regardless -- but has no
        # phase caption, no base coordinate and no injection count, with
        # nothing on it explaining why.
        if not os.path.isdir(T):
            print(f"WARNING: {T} is not a directory. The phase caption, the "
                  "base coordinate and the injection count all come from logs "
                  "there and will stay blank.", file=sys.stderr)
            if os.name == "nt":
                print(r"  On Windows against a chain running in WSL, pass "
                      r"--scratch \\wsl$\Ubuntu\tmp\rtk-loop"
                      " -- or just run this inside WSL, which is the path "
                      "that has been tested.", file=sys.stderr)
        record = args.record or os.path.join(T, "view.jsonl")
        threads += [
            threading.Thread(target=nmea_reader,
                             args=(st, host, int(port), stop), daemon=True),
            threading.Thread(target=truth_reader,
                             args=(st, args.truth, stop), daemon=True),
            threading.Thread(target=watch_flight,
                             args=(st, os.path.join(T, "flight.log"), stop),
                             daemon=True),
            threading.Thread(target=watch_relay,
                             args=(st, os.path.join(T, "relay.log"), stop),
                             daemon=True),
            threading.Thread(target=watch_rtklib,
                             args=(st, os.path.join(T, "rtklib.log"), stop),
                             daemon=True),
            threading.Thread(target=watch_trigger,
                             args=(st, os.path.join(T, "attack.go"), stop),
                             daemon=True),
            threading.Thread(target=pump_live,
                             args=(st, hub, stop, args.rate, record),
                             daemon=True),
        ]
        print(f"observing NMEA {args.nmea}, truth {args.truth}, logs in {T}")
        print(f"recording frames to {record}")

    for t in threads:
        t.start()

    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer((args.bind, args.port), make_handler(hub, page))
    srv.daemon_threads = True
    print(f"view on http://localhost:{args.port}/   (ctrl-c to stop)")
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
