#!/usr/bin/env python3
"""
Minimal client for rtkrcv's own telnet console -- the same interface a real
operator would use, not memory inspection or a debugger.

    rtkrcv_console.py [--host H] [--port P] [--password PWD] cmd [cmd...]

Prints each command's raw response to stdout, in order. Login happens
automatically first if --password is set (rtkrcv's console prompts for one
on connect whenever console-passwd is non-empty in its .conf).
"""
import argparse
import socket
import sys
import time


def read_all(sock, settle=0.5):
    buf = b""
    sock.settimeout(settle)
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    return buf


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="+", help="console command(s), sent in order")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--password", default="admin")
    ap.add_argument("--quiet", action="store_true", help="only print the last command's response")
    args = ap.parse_args()

    s = socket.create_connection((args.host, args.port), timeout=5)
    read_all(s)  # banner + password prompt

    if args.password:
        s.sendall((args.password + "\r\n").encode())
        read_all(s)

    for i, c in enumerate(args.cmd):
        s.sendall((c + "\r\n").encode())
        resp = read_all(s, settle=1.0).decode(errors="replace")
        if not args.quiet or i == len(args.cmd) - 1:
            print(f"=== {c} ===")
            print(resp)

    s.close()


if __name__ == "__main__":
    main()
