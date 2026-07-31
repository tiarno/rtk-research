#!/usr/bin/env python3
"""Keep the NMEA link *up* after the upstream producer dies.

Why this exists. When RTKLIB is built fortified, the malicious 1033 aborts the
process. Pointing SITL's GPS serial port straight at RTKLIB's TCP server then
measures the wrong thing: the socket closes, SITL retries the port a handful of
times, and the *simulator* exits before ArduPilot's GPS/EKF failsafe logic ever
runs. That is a harness artifact, not aircraft behaviour.

A real receiver on a real UART that crashes does not take the serial port down
with it. The wires stay connected and the bytes simply stop. This proxy
reproduces that: it forwards upstream->client normally, and when the upstream
producer dies it holds the client socket open and sends nothing at all.

    ./nmea_hold.py --listen 5904 --upstream 127.0.0.1:5903 --seconds 260

Transparent while the producer is alive, so the same flag can be used on an
unfortified control run to prove the proxy itself changes nothing.
"""
import argparse
import socket
import sys
import time


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, required=True)
    ap.add_argument("--upstream", required=True, help="host:port")
    ap.add_argument("--seconds", type=float, default=260.0)
    args = ap.parse_args()

    up_host, up_port = args.upstream.rsplit(":", 1)
    up_addr = (up_host, int(up_port))

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", args.listen))
    srv.listen(1)
    log(f"listening on :{args.listen}, upstream {args.upstream}")

    deadline = time.time() + args.seconds
    srv.settimeout(max(1.0, deadline - time.time()))
    try:
        cli, peer = srv.accept()
    except socket.timeout:
        log("no client connected before deadline")
        return 1
    log(f"client connected from {peer}")

    # Connect upstream only once the client is here, and retry: RTKLIB's server
    # may not have accepted yet.
    up = None
    for _ in range(40):
        try:
            up = socket.create_connection(up_addr, timeout=2.0)
            break
        except OSError:
            time.sleep(0.25)
    if up is None:
        log(f"FAILED: could not reach upstream {args.upstream}")
        cli.close()
        return 1
    log("upstream connected; forwarding")

    up.settimeout(0.5)
    total = 0
    died_at = None
    while time.time() < deadline:
        if up is not None:
            try:
                data = up.recv(4096)
            except socket.timeout:
                continue
            except OSError as e:
                log(f"upstream error: {e}")
                data = b""
            if not data:
                # This is the event under measurement. Do NOT close cli.
                died_at = time.time()
                log(f"UPSTREAM GONE after {total} bytes -- "
                    f"holding the client socket open, sending nothing")
                try:
                    up.close()
                except OSError:
                    pass
                up = None
                continue
            try:
                cli.sendall(data)
            except OSError as e:
                log(f"client gone: {e}")
                break
            total += len(data)
        else:
            # Producer is dead. Hold the line up and stay silent, which is what
            # a crashed receiver looks like from the far end of a UART.
            time.sleep(0.25)

    if died_at is not None:
        log(f"held the line open for {time.time() - died_at:.1f}s after "
            f"the producer died")
    else:
        log(f"producer outlived the run; forwarded {total} bytes")
    try:
        cli.close()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
