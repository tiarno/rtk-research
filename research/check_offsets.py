#!/usr/bin/env python3
"""
Does the payload length measured on x86-64 transfer to other architectures?

The attack works because a declared length runs a copy past the end of a text
field in sta_t and into `double pos[3]`, the base station's own coordinate. How
many bytes that takes is offsetof(sta_t,pos) minus the offset of the field
being copied into -- and both are decided by the target ABI's alignment rules,
not by RTKLIB's source. Debian ships RTKLIB for twelve architectures. Claiming
"the same payload works" on any of them is a claim about ABIs, and it was
unverified: every offset in this repo had been computed against x86-64.

Nothing has to run on the target. The compiler already knows the offset at
translation time, so each candidate is put to it as a _Static_assert and the
answer is read off compile success. Bisection, so it costs ~12 compiles per
field rather than a scan. The number therefore comes from a real toolchain's
ABI implementation rather than from alignment arithmetic done here, which is
the part that could be wrong.

    python3 check_offsets.py [RTKLIB_SRC]

Cross-compiler is `zig cc`, which is clang carrying a full set of targets and
installs without root:

    python3 -m pip install --user ziglang

x86-64 is measured twice, once with the system gcc and once through zig. They
must agree, and they must both reproduce the 464 this repo measured by other
means. If the control disagrees the method is untrustworthy and so is
everything it reports about the other targets -- the script says so and stops.
"""
import os
import subprocess
import sys
import tempfile

FIELDS = ["rectype", "pos", "del", "hgt"]

# Debian builds RTKLIB for these among others; armel is included because it is
# the interesting negative -- soft-float, and still 8-byte double alignment,
# because that is AAPCS rather than a property of the FPU.
TARGETS = [
    ("x86_64-linux-gnu",   "x86-64  64-bit"),
    ("arm-linux-gnueabihf", "armhf   32-bit hard-float"),
    ("arm-linux-gnueabi",  "armel   32-bit soft-float"),
    ("aarch64-linux-gnu",  "arm64   64-bit"),
    ("riscv64-linux-gnu",  "riscv64 64-bit"),
    ("powerpc64-linux-gnu", "ppc64   64-bit"),
]

KNOWN_X86_64 = {"rectype": 256, "pos": 464, "del": 488, "hgt": 512}


def zig(*args):
    return subprocess.run([sys.executable, "-m", "ziglang", "cc", *args],
                          capture_output=True, text=True)


def probe(src_dir, target, tmp, expr):
    src = os.path.join(tmp, "probe.c")
    with open(src, "w") as fh:
        fh.write('#include <stddef.h>\n#include "rtklib.h"\n'
                 f'_Static_assert({expr}, "probe");\nint probe_tu;\n')
    r = zig("-target", target, "-I", src_dir, "-c", src,
            "-o", os.path.join(tmp, "probe.o"), "-w")
    return r.returncode == 0, r.stderr


def bisect(src_dir, target, tmp, what, hi=4096):
    """Smallest N with `what < N`; the value is N-1."""
    ok, err = probe(src_dir, target, tmp, f"{what} < {hi}")
    if not ok:
        return None, err
    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        ok, _ = probe(src_dir, target, tmp, f"{what} < {mid}")
        if ok:
            hi = mid
        else:
            lo = mid + 1
    return lo - 1, ""


def gcc_control(src_dir, tmp):
    """Independent reading of the same numbers, from a different compiler."""
    src, exe = os.path.join(tmp, "off.c"), os.path.join(tmp, "off")
    with open(src, "w") as fh:
        fh.write('#include <stdio.h>\n#include <stddef.h>\n#include "rtklib.h"\n'
                 'int main(void){printf("%zu %zu %zu %zu %zu\\n",'
                 + ",".join(f"offsetof(sta_t,{f})" for f in FIELDS)
                 + ',sizeof(sta_t));return 0;}\n')
    if subprocess.run(["gcc", "-I", src_dir, "-o", exe, src],
                      capture_output=True).returncode != 0:
        return None
    out = subprocess.run([exe], capture_output=True, text=True).stdout.split()
    return [int(x) for x in out]


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "RTKLIB", os.path.expanduser("~/RTKLIB")) + "/src"
    if not os.path.isfile(os.path.join(src_dir, "rtklib.h")):
        sys.exit(f"no rtklib.h in {src_dir} -- pass the src directory")

    if zig("--version").returncode != 0:
        sys.exit("zig cc unavailable. python3 -m pip install --user ziglang")

    with tempfile.TemporaryDirectory() as tmp:
        gcc = gcc_control(src_dir, tmp)
        if gcc:
            print("control, system gcc on x86-64:")
            print("  " + "  ".join(f"{f}={v}" for f, v in zip(FIELDS, gcc))
                  + f"  sizeof={gcc[-1]}")
            bad = [f for f, v in zip(FIELDS, gcc) if KNOWN_X86_64[f] != v]
            if bad:
                sys.exit(f"control DISAGREES with this repo's measured values "
                         f"on {bad} -- stopping, the header may have changed")
            print("  agrees with the values measured elsewhere in this repo\n")
        else:
            print("(no system gcc; zig's x86-64 result is the only control)\n")

        print(f"{'target':<28} " + "".join(f"{f:>9}" for f in FIELDS)
              + f"{'sizeof':>9}")
        print("-" * 82)
        rows = {}
        for target, label in TARGETS:
            vals = []
            for f in FIELDS:
                v, err = bisect(src_dir, target, tmp, f"offsetof(sta_t,{f})")
                vals.append(v)
            size, _ = bisect(src_dir, target, tmp, "sizeof(sta_t)")
            if None in vals or size is None:
                print(f"{label:<28} (target unavailable)")
                continue
            rows[target] = vals + [size]
            print(f"{label:<28} " + "".join(f"{v:>9}" for v in vals)
                  + f"{size:>9}")

        base = rows.get("x86_64-linux-gnu")
        if not base:
            sys.exit("\nno x86-64 result: nothing to compare against")
        if gcc and base != gcc:
            sys.exit("\nzig and gcc DISAGREE on x86-64 -- method is unsound")

        print()
        differ = [l for t, l in TARGETS
                  if t in rows and t != "x86_64-linux-gnu" and rows[t] != base]
        if differ:
            for label in differ:
                print(f"DIFFERS from x86-64: {label}")
            print("\nThe payload length does NOT transfer unchanged to the "
                  "targets above.\nRecompute n1 for each before claiming it "
                  "does.")
        else:
            n = len(rows) - 1
            print(f"All {n} non-x86-64 targets have an IDENTICAL sta_t layout.")
            print("offsetof(sta_t,pos) = %d everywhere, because AAPCS and the "
                  "other\nABIs here all align double to 8 bytes -- including "
                  "soft-float armel,\nwhere it is an ABI rule rather than a "
                  "property of the FPU." % base[1])
            print("\nSo the payload lengths measured on x86-64 transfer "
                  "unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
