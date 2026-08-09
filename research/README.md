# `decode_type1033` — station position corruption

Reproduction harness for a station-position attack against RTKLIB's RTCM3
type 1033 decoder.

**Measured against:** `tomojitakasu/RTKLIB`, branch `rtklib_2.4.3`, commit
`180043e` (2.4.3 b34, 2020-12-29). The same code is present unchanged on
`master` (2.4.2 p13, 2018-01-30).

---

## Summary

A single well-formed RTCM3 type 1033 message — correct length field, correct
CRC24Q, valid station ID — corrupts a rover's base-station coordinates. The
declared length selects the *scale* of the error, not its value: each extra
zeroed byte multiplies the truncation quantum by 256, giving a handful of
usable rungs from imperceptible, through a silent metre-scale error, up to
total loss of solution. One rung (`n1=211`, a 2 m quantum) bounds the error
under 2 m against **any** base station, with no knowledge of its coordinates.

**Which of two things happens depends on how the binary was compiled**, and
this turns out to be the most important fact here:

| build | outcome |
|---|---|
| glibc `_FORTIFY_SOURCE` active (`-O1`+ and the flag actually reaching the compiler) | the fortified `strncpy` detects the overflow and **aborts the process** — a remote DoS, repeatable for as long as the stream continues. On a vehicle this is a **second attack, not a mitigation**: the aircraft loses GPS, cannot return home, and lands within ~10 m of wherever the attacker chose to send the packet |
| unfortified — **every build measured so far**: both Windows distributions, and Debian's own `rtklib` package on ARM | the write goes through **silently** — position corruption |

In the unfortified case the interesting band is a small one. A shift of
~0.4-2.5 m leaves RTKLIB reporting **Q=1 (RTK fixed)** — its highest quality
flag — while the position it emits is wrong by roughly the amount injected.
Nothing crashes, no log records the coordinate changing, and AddressSanitizer
reports nothing.

That is the answer to the question the project started from: *can an attacker
manipulate a precision GNSS rover while it continues to report a healthy fix?*
Yes, and via a software path rather than RF — on the builds least likely to be
hardened, which is precisely the RTKLIB-derived firmware class.

## The mechanism

`decode_type1033` reads five descriptor strings, each an 8-bit length followed
by that many characters. It stages them in 32-byte locals with correctly
bounded read loops, then copies them into `rtcm->sta` with the *unbounded*
declared length ([src/rtcm3.c:1016-1021](https://github.com/tomojitakasu/RTKLIB/blob/rtklib_2.4.3/src/rtcm3.c#L1016)):

```c
strncpy(rtcm->sta.rectype,rec,n1); rtcm->sta.rectype[n1]='\0';   /* :1019 */
```

`n1` comes straight off the wire, so it ranges 0-255 against a 64-byte field.

### The write is zeros, not attacker bytes

FuzzingLabs' report is precise about this — it says "out-of-bounds write of
attacker-controlled *length*", not of attacker-controlled content. The claim
that the ~191 overflow bytes can be filled with a chosen pattern is an
extrapolation made in [the local briefing](../docs/rtklib-claude-code-briefing.md)
(Task 1, "fill the overflow bytes De Bruijn-style"), not something FuzzingLabs
asserted. It does not hold:

The staging buffers are `char rec[32]=""` and the read loop is bounded at
`j<n1&&j<31`, so at most 31 attacker bytes ever reach them and byte 31 is
always NUL. `strncpy` copies to that NUL and **zero-pads the remainder**:

| destination range | content |
|---|---|
| `[0, 31)` | attacker-controlled (in bounds — the field is 64 bytes) |
| `[31, n1)` | zeros (strncpy padding) |
| `[n1]` | zero (explicit) |

Every out-of-bounds byte is zero. This is a **zeroing primitive**, not an
arbitrary write. No attacker-chosen value can be placed out of bounds.

### A second defect: a length above 31 misaligns the rest of the message

Separate from the overflow, found while verifying the clamp below, and not in
FuzzingLabs' report. The five length bytes are read with absolute bit offsets
computed from the declared lengths, so those are always correct. The sequential
walk that follows is not:

```c
for (j=0;j<n&&j<31;j++) { des[j]=getbitu(rtcm->buff,i,8); i+=8; }
setup=getbitu(rtcm->buff,i, 8); i+=8+8;
```

`i` advances by at most 31 bytes while the wire format carries the full
declared length, so any length above 31 leaves the walk short by `len-31` bytes
and **every field after it is parsed from the wrong offset**.

Measured (`misalign_check.py`) with `antdes` declared at 40 and everything else
ordinary — control at 20 in the same run:

| | expected | antdes=20 | antdes=40 |
|---|---|---|---|
| `antsetup` | 7 | 7 | **68** (`0x44`, the 32nd descriptor byte) |
| `rectype` | `TRIMBLE NETR9` | `TRIMBLE NETR9` | **`NO-ALPHA.TRIM`** |
| `recsno` | `RSN-OMEGA` | `RSN-OMEGA` | **`TR9.5.22.`** |

Displaced by exactly the 9 bytes the walk fell short. Note the field *lengths*
stay correct, because those come from the absolute-offset reads — only the
contents shift, so the result is plausible-looking garbage rather than an
obvious parse failure.

Two things this is not. It is **not** a memory-safety issue — every read stays
inside the frame. And it does **not** affect the station-position attack, which
oversizes `rectype`: everything that attack depends on is parsed before the
walk reaches that field. It bites when an *earlier* field is oversized. It is
also unaffected by the clamp — the clamp stops the write, not the walk.

### What each field reaches

Measured on x86-64 / gcc. `sizeof(sta_t)` is 560; `sta` sits at
`offsetof(rtcm_t,sta)==237408` and the `dgps` pointer immediately follows it.

| descriptor | offset in `sta_t` | reach at len=255 | zeroes |
|---|---|---|---|
| `antdes` | 128 | 383 | antsno, rectype, recver |
| `antsno` | 192 | 447 | rectype, recver, recsno |
| `rectype` | 256 | 511 | recver, recsno, antsetup, itrf, deltype, **`pos[3]`**, `del[3]` |
| `recver` | 320 | 575 | above + hgt, glo_cp_*, 16B past `sta_t` → `dgps` |
| `recsno` | 384 | 639 | above + 79B past `sta_t` → `dgps` + 71B into `ssr[]` |

Maximum reach is 639 bytes from a struct base sitting ~237 KB inside a
~240 KB `rtcm_t`. **The overflow never escapes `rtcm_t`** — no heap metadata,
no saved return address, no function pointer, no adjacent allocation.

### `decode_type1007`/`1008`: same shape, measured to not reach `pos`

FuzzingLabs' report also notes the same unclamped-length pattern in
`decode_type1007` and `decode_type1008` (see "Relationship to the FuzzingLabs
disclosure" below), without saying where it lands. Read at
[src/rtcm3.c:504](https://github.com/tomojitakasu/RTKLIB/blob/rtklib_2.4.3/src/rtcm3.c#L504)
and [:537](https://github.com/tomojitakasu/RTKLIB/blob/rtklib_2.4.3/src/rtcm3.c#L537),
both carry it — `decode_type1007` writes `antdes` via an unbounded
`strncpy(rtcm->sta.antdes,des,n)`; `decode_type1008` writes both `antdes` and
`antsno` the same way. Same read/write asymmetry as 1033 too: the read loop
caps at 31 bytes, `strncpy` copies to that NUL and zero-pads out to the full
declared `n`/`m` — a truncation primitive, not a controlled write, exactly as
for `rectype`.

The table above already answers where it lands: `antdes` sits at offset 128,
`antsno` at 192. Their maximum reach at the largest legal declared length
(255) is 383 and 447 — short of `pos` at 464 by 81 and 17 bytes respectively,
and short of the end of `sta_t` itself (560 bytes) by 177 and 113. Neither
field can reach `pos`, and neither can escape `sta_t` into `dgps` the way
1033's `recsno` does. That's arithmetic on measured offsets, not yet a
measurement of the real decoder — `check_1007_1008.py` is that measurement,
built the same way as everything above: generate well-formed 1007/1008
frames with `antdes`/`antsno` declared at 255, run them through the real
`input_rtcm3`, and check `sta.pos` and the `dgps` sentinel afterward.

```
1007, antdes=255    sta.pos = -2694685.4730 -4293642.3660 3857878.9240   dgps = 0x4141414141414141
1008, antdes=255    sta.pos = -2694685.4730 -4293642.3660 3857878.9240   dgps = 0x4141414141414141
1008, antsno=255    sta.pos = -2694685.4730 -4293642.3660 3857878.9240   dgps = 0x4141414141414141
```

Confirmed, not just predicted: `sta.pos` stays at truth and the `dgps`
sentinel stays intact in every case. `decode_type1007` and `decode_type1008`
share the exact same missing-clamp shape as `decode_type1033` — same
zero-padding truncation primitive, same self-triggering absence of a bounds
check — but `antdes` and `antsno` are placed too early in `sta_t` to reach
`pos`, or to leave the struct at all, at any legal declared length. **Memory
safety only, in-struct only, no positioning impact, on either type.** That
answers "why 1033?": of the five descriptor fields across all three message
types, `rectype`, `recver` and `recsno` are the only ones positioned after
`pos` — and all three belong to 1033, since 1007/1008 don't carry a receiver
descriptor at all, only antenna ones.

## Why this is a positioning bug, not a memory-safety bug

`rectype` with `n1 >= 209` zeroes `sta.pos[3]` — the base-station ECEF
coordinates — entirely *within* the bounds of `sta_t`. No memory-safety rule
is broken by that write at all.

Then it self-triggers. `decode_type1033` returns `5`; `rtksvr.c:325` dispatches
`ret==5` to `update_antpos()`, which at `rtksvr.c:251` does:

```c
for (i=0;i<3;i++) svr->rtk.rb[i]=sta->pos[i];   /* no validation */
```

The post-processing path guards this with `norm(sta[i].pos,3)>0.0`
(`postpos.c:843`). **The real-time server path has no such guard.** So one
message both corrupts the base position and triggers its adoption into the
baseline.

### Which configurations are exposed

Requires `refpos=POSOPT_RTCM` — the base position taken from the correction
stream rather than entered by hand. That is **not** RTKLIB's compiled default:
`options.c:503` initialises `antpostype_` to 0 (LLH). But it is what the
shipped RTK example tells you to use.

Of the six example configurations in the source tree, exactly one is set up for
real-time RTK against an RTCM3 stream — and it is also the only one that
selects the vulnerable setting:

| config | `pos1-posmode` | `inpstr2-format` | `ant2-postype` |
|---|---|---|---|
| `app/consapp/rtkrcv/conf/rtk.conf` | kinematic | **rtcm3** | **rtcm** |
| `app/consapp/rtkrcv/conf/single.conf` | single | — | llh |
| `app/consapp/rtkrcv/gcc/rtkrcv.conf` | single | oem4 | llh |
| `app/consapp/rnx2rtkp/gcc/opts1.conf` | static | post-processing | single |
| `app/consapp/rnx2rtkp/gcc/opts2.conf` | kinematic | post-processing | llh |
| `app/consapp/rnx2rtkp/gcc/opts3.conf` | kinematic | post-processing | llh |
| `app/consapp/rnx2rtkp/gcc/opts4.conf` | static | post-processing | llh |

`ant2-postype=rtcm` is option 5, which `options.c:409` (`*ps=antpostype_[i]-1`,
with `ps` bound to `prcopt_.refpos` for index 1) maps to `refpos=4` —
`POSOPT_RTCM`.

So the honest statement is narrower than "the normal RTK configuration" and
also stronger than a default would be. The other six are single-point or
post-processing modes, which have no live correction stream to take a base
position from in the first place. **The one shipped configuration that does
real-time RTK is the vulnerable one**, because taking the base coordinate from
the stream is part of what makes it RTK rather than something an operator opted
into.

**Not checked:** what RTKNAVI's GUI selects on a fresh install, what demo5
ships, and what Emlid Reach's web UI configures. Those want measuring before
any claim about the configuration of deployed receivers.

## Results

```
======== benign.bin ========            legitimate 1005 + normal 1033
    sta.pos  = -2694685.4730 -4293642.3660 3857878.9240
    rtcm.dgps = 0x4141414141414141
    -> adopted into rtk.rb = -2694685.4730 -4293642.3660 3857878.9240

======== attack.bin ========            1005 + 1033 with rectype len=255
    sta.pos  = 0.0000 0.0000 0.0000
    rtcm.dgps = 0x4141414141414141     <- untouched: write stayed inside sta_t
    -> adopted into rtk.rb = 0.0000 0.0000 0.0000

======== oob.bin ========               1005 + 1033 with recsno len=255
    sta.pos  = 0.0000 0.0000 0.0000
    rtcm.dgps = (nil)                  <- clobbered: write ran past sta_t
    -> adopted into rtk.rb = 0.0000 0.0000 0.0000
```

`dgps` is seeded with a `0x41` sentinel because `init_rtcm()` leaves it NULL,
which would hide the corruption.

### The length byte selects the magnitude

The write is a contiguous prefix starting at `rectype+31`, so the declared
length selects how many low-order bytes of `pos[0]` (then `pos[1]`, then
`pos[2]`) get zeroed. On little-endian x86 those are mantissa bytes, so short
overwrites perturb the coordinate slightly and long ones destroy it:

```
n1=208      sta.pos = -2694685.4730 -4293642.3660 3857878.9240   (sub-micron)
n1=212      sta.pos = -2694656.0000 -4293642.3660 3857878.9240   (29.5 m)
n1=215      sta.pos =       0.0000 -4293642.3660 3857878.9240
n1=223      sta.pos =       0.0000        0.0000 3857878.9240
n1=255      sta.pos =       0.0000        0.0000       0.0000
```

### The dial has four rungs, and 211 is the one that generalises

Calling it a dial oversells it. Each additional zeroed byte multiplies the
truncation quantum by 256, so between "no effect" and "no solution" there are
only a handful of settings. Measured through the real decoder, base ECEF
X = -2694685.4730:

| `n1` | bytes of `pos[0]` zeroed | truncation quantum | resulting `pos[0]` | error |
|---|---|---|---|---|
| 208 | 1 | 0.12 µm | -2694685.4730 | — |
| 209 | 2 | 31 µm | -2694685.4730 | — |
| 210 | 3 | 7.8 mm | -2694685.4688 | 0.004 m |
| **211** | **4** | **2 m** | **-2694684.0000** | **1.473 m** |
| 212 | 5 | 512 m | -2694656.0000 | 29.47 m |
| 213 | 6 | 131 km | -2621440.0000 | 73.2 km |
| 214 | 7 | 33.6 Mm | -131072.0000 | 2564 km |

The attacker chooses the *scale*, not the value. Within a rung the error is
whatever the truncated low bits of the true coordinate happen to be —
effectively uniform in `[0, quantum)` and not controllable, since the write is
always zeros and truncation is always toward zero.

**That makes `n1=211` the setting worth quoting.** Zeroing exactly four bytes
quantises ECEF X to `2^32 × ulp(X)`, which for any Earth-surface coordinate
(|X| ≤ 6378 km) is between 0.5 m and 4 m — for both bases measured here,
exactly 2 m. So the induced error is bounded by one quantum: **always large
enough to matter to an RTK user, never large enough to lose the solution, for
any base station anywhere.** No knowledge of the base coordinates is required.
The error for the two bases tested is 1.47 m and 0.43 m.

`n1=212` is the opposite: a 512 m quantum, so the outcome is a coin toss. It
gives 2.435 m against the original end-to-end base and 29.5 m against this one,
where it would simply be rejected. **The 2.4 m figure that headlined this work
is that die landing well, not a magnitude the attacker selected.**

The live demo has since been moved onto `n1=211` for exactly this reason, with
the base sited so the reliable rung is also a visible one — see "The demo runs
at `n1=211`" below. The 212 runs are retained as the cross-validation against
the open-loop measurement, not as the demo configuration.

### The same dial on the binaries people actually run

Everything above is a local gcc build, which leaves the question of which
column — abort or silent corruption — the *shipped* binaries fall into. Both
of the distributions in common use fall into the silent one, measured rather
than inferred.

Tested on Windows 11: `convbin.exe` from
[tomojitakasu/RTKLIB_bin](https://github.com/tomojitakasu/RTKLIB_bin)
`master`, the official Windows distribution, and from
[rtklibexplorer](https://github.com/rtklibexplorer/RTKLIB/releases) release
`RTKLIB_EX_2.5.1` — the "demo5" fork most low-cost-receiver users run.
Downloaded 2026-07-26; SHA-256 prefixes `2207b9460862fc1a` and
`245647b373cdc95f`. `convbin` decodes RTCM3 through the same
`input_rtcm3` → `decode_type1033` path and writes the decoded station
coordinate into its RINEX header, so the corruption is readable straight out
of the output file. Streams are the ones `inject_1033.py` produces.

| declared `n1` | official (32-bit) `pos[0]` | demo5 2.5.1 (64-bit) `pos[0]` | rc |
|---|---|---|---|
| 205 | -3978242.4348 | -3978242.4348 | 0 |
| 208 | -3978242.4348 | -3978242.4348 | 0 |
| 210 | -3978242.4297 | -3978242.4297 | 0 |
| 212 | **-3978240.0000** | **-3978240.0000** | 0 |
| 215 | 0.0000 | 0.0000 | 0 |
| 223 | 0.0000 (and `pos[1]`) | 0.0000 (and `pos[1]`) | 0 |
| 255 | all three zeroed | all three zeroed | 0 |

Truth is -3978242.4348. Three things follow.

**Nothing crashes — and not because a check was left switched off.**
`_FORTIFY_SOURCE` is a glibc feature. Both binaries are Embarcadero C++
Builder executables against the Windows CRT, and neither imports any `*_chk`
function, so the fortified `strncpy` that aborts a Linux build has no
equivalent here to switch on. The abort column is the Linux-build column; on
Windows there is only the silent one. Every run above exits 0.

**The magnitude dial reproduces to the last digit** on real distributions,
including the 5 mm perturbation at `n1=210` and the 2.4 m one at 212.

**32-bit and 64-bit behave identically**, which refines a caveat listed under
Limitations. Everything in `sta_t` ahead of `pos` is `char` arrays and `int`s
(448 + 12 = 460, padded to 464 for 8-byte alignment), so `pos` sits at the
same offset in both ABIs and a single payload length works across both. That
equivalence is measured on these two builds — and has since been measured
directly across six ABIs, including ARM, all of which put `pos` at 464. See
"The payload length transfers unchanged".

Both distributions also ship the real-time applications `rtknavi.exe` and
`strsvr.exe`, and those binaries contain the same decoder — the trace strings
`rtcm3 1033 length error: len=%d` and `rtcm3 1033: ant=%s:%s rec=%s:%s:%s` are
present in each. They are GUI programs and were not driven here. So what is
measured on Windows is the decode and the coordinate corruption; the
subsequent adoption into the baseline by `update_antpos()` is measured on the
Linux build only.

Demo5 shipped 2.5.1 on 2026-06-22, **13 days after** the FuzzingLabs issues
were filed, with the bug unchanged.

### A shipping receiver runs this code: Emlid Reach

Everything above is desktop software. The question that decides whether this is
a library bug or a *product* bug is whether any receiver you can buy runs the
vulnerable decoder. One does.

[`emlid/RTKLIB`](https://github.com/emlid/RTKLIB) is Emlid's fork, described by
them as "used in Reach RTK receiver". Read on branch `reach` (also `master`;
last pushed 2021-06-02), fetched 2026-07-26:

- **`decode_type1033` is unchanged.** All five `strncpy` calls carry the same
  wire-supplied lengths against the same 32-byte staging buffers, including the
  `rectype`/`n1` line — the one field of the three that reaches `pos` and the
  one FuzzingLabs' PoC does not drive.
- **`sta_t` has the same layout ahead of `pos`.** `MAXANT` is 64, and the seven
  `char[MAXANT]` arrays plus three `int`s precede `pos[3]` exactly as upstream,
  so `pos` sits at offset 464 and **the same `n1` payloads work unmodified** —
  no recomputation for this target. (Their `sta_t` drops `glo_cp_align` and
  `glo_cp_bias` from the tail, which is after `pos` and does not matter.)
- **The unvalidated adoption survives, inlined.** Emlid folded
  `update_antpos()` into `updatesvr()` (`rtksvr.c:219`), where `ret==5` still
  does the same thing with no plausibility check:

```c
else if (ret==5) { /* antenna position parameters */
    if (svr->rtk.opt.refpos==POSOPT_RTCM&&index==1) {
        for (i=0;i<3;i++) {
            svr->rtk.rb[i]=svr->rtcm[1].sta.pos[i];
        }
```

  `postpos.c:1038` still guards the post-processing path with
  `norm(sta[i].pos,3)>0.0`. The same asymmetry as upstream: the real-time path
  is the unguarded one.

### The distro package is unfortified too, and it is ARM

Chasing the Reach binary turned up something better on the way. Emlid's Navio
image ships no RTKLIB at all (checked: the only hits in a 3.7 GB rootfs are
OpenLDAP symbols matching `str2str` as a substring, plus one APT metadata
stanza) — but that stanza revealed that **Debian packages RTKLIB**, and the
packaged version is `2.4.3.b34+dfsg`, the exact upstream release measured here.
It is built for **12 architectures**: amd64, arm64, armel, armhf, i386,
loong64, mips64el, mipsel, ppc64el, riscv64, s390x.

Measured on `rtklib_2.4.3.b34+dfsg-1+b2_armhf.deb` from the Debian pool:

| | |
|---|---|
| binaries | `rtkrcv`, `str2str`, `convbin`, `rnx2rtkp`, `pos2kml` |
| format | ELF 32-bit LSB, **ARM EABI5** |
| decoder location | statically linked *inside* each app — `rtkrcv` needs only `libm`/`libc`, and carries the `rtcm3 1033 length error` and `ant=%s:%s rec=%s:%s:%s` trace strings |
| `__strncpy_chk` | **absent** |
| any `*_chk` import | **none at all** |
| plain `strncpy`/`strcpy`/`sprintf`/`memcpy`/`fprintf` | all present |

Plain names present and zero fortified variants is the signature of a build
without `_FORTIFY_SOURCE`. Had it been active, `strncpy` into a known-size
`char[64]` with a runtime length is exactly the call that becomes
`__strncpy_chk`, and `sprintf`/`fprintf` would have gone the same way.

**This refutes a prediction made earlier in this work.** The expectation was
that Linux targets — distro packages and Linux-based receivers — would land in
the *fortified* column, aborting rather than corrupting, opposite the Windows
desktop applications. They do not. Debian's own package escapes the hardening
its distro policy nominally applies, presumably because RTKLIB's upstream
makefiles override the injected `CFLAGS`. So `apt install rtklib` on
Debian/Raspbian, on ARM, is in the **silent corruption** column with everything
else.

The abort column is now looking like the exception rather than the rule: it is
what you get by compiling it yourself with the right flags, and not what any
build measured so far — two Windows distributions and one Linux/ARM distro
package — actually does.

That also supplies the first real ARM binary in this work, which weakens the
case for the qemu offset exercise: ARM builds exist, ship, and are unfortified.

### The payload length transfers unchanged — measured, six ABIs

Everything above was an argument about *fortification*. A separate question
had been left open: whether the payload lengths measured here mean anything on
another architecture at all. They are derived from `offsetof(sta_t,pos)`, and
that offset is decided by the target ABI's alignment rules rather than by
RTKLIB's source, so "the same payload works" was a claim about ABIs that had
only ever been checked against x86-64.

Measured with `check_offsets.py`, which needs nothing to run on the target: the
compiler already knows the offset at translation time, so each candidate value
is put to it as a `_Static_assert` and the answer is read off compile success.

| target | `rectype` | `pos` | `del` | `hgt` | `sizeof` |
|---|---|---|---|---|---|
| x86-64 | 256 | **464** | 488 | 512 | 560 |
| armhf 32-bit hard-float | 256 | **464** | 488 | 512 | 560 |
| armel 32-bit soft-float | 256 | **464** | 488 | 512 | 560 |
| arm64 | 256 | **464** | 488 | 512 | 560 |
| riscv64 | 256 | **464** | 488 | 512 | 560 |
| ppc64 | 256 | **464** | 488 | 512 | 560 |

Identical on all six, because every ABI here aligns `double` to 8 bytes. The
one worth calling out is **armel**: soft-float, no FPU in the ABI at all, and
still 8-byte alignment, because that is what AAPCS specifies rather than a
property of the hardware. The obvious way for this to have differed — a target
that aligns `double` to 4 — does not occur among the architectures Debian
ships RTKLIB for.

So `n1=211` is not an x86-64 number. It is the number, on every architecture
checked.

*Control:* the same offsets read independently with the system gcc, which
reproduces the 464 measured elsewhere in this repo by other means. `zig cc`
(clang) and gcc agree exactly; the script stops rather than report anything if
they do not, because a method whose control disagrees is not measuring
anything.

**Why this matters more than the desktop result.** ArduPilot documents Reach as
a supported RTK GPS: the unit mounts on the vehicle, outputs coordinates to the
flight controller over serial in Emlid's ERB protocol, and — per ArduPilot's own
page — "can receive base corrections over telemetry radio, thus not requiring a
separate correction link to the drone." That is the chain this harness
simulates, with a real product in the receiver position and an unauthenticated
radio link carrying the corrections into it.

**What is not established: which column the shipped binary falls into.** The
source is vulnerable; whether Emlid's build has `_FORTIFY_SOURCE` active
decides between a silent 2 m corruption and one packet killing the receiver.
Both are results and neither is measured. The image is not casually obtainable
— `files.emlid.com` returns 403 for image paths and directory listings, the
Reach Firmware Flash Tool fetches the image at runtime rather than publishing a
URL, and the Wayback Machine holds only Emlid's *Navio* Raspbian images, which
are a different product and not confirmed to ship RTKLIB binaries at all.
Settling it needs either the flash tool's fetch observed or the hardware.

### Effect on the solution

Feeding those magnitudes to RTKLIB's own positioning engine (`rnx2rtkp`,
kinematic, rover `0759` / base `3040` from `test/data/rinex`):

| base position | epochs solved | first solution | quality |
|---|---|---|---|
| truth | 115 | 35.160875019, 139.613838551, 70.2724 | **Q=1 fixed** |
| low 4B zeroed (0.44 m off) | 115 | 35.160876738, 139.613835459, 70.0019 | **Q=1 fixed** |
| low 5B zeroed (2.4 m off) | 115 | 35.160884646, 139.613821236, 68.7576 | **Q=1 fixed** |
| low 6B zeroed (46 km off) | 0 | — | no solution |
| `pos[0]=0` (3978 km off) | 0 | — | no solution |
| all zero | 0 | — | no solution |

The base-position error propagates into the rover's reported position roughly
one-for-one, and the quality flag stays at 1 throughout the useful range. A
receiver claiming a centimetre-grade fixed solution is emitting a position
metres away from truth.

Large corruptions are caught, but only incidentally: `zdres()` in `rtkpos.c`
bails on `if (norm(rr,3)<=0.0)`, and grossly wrong geometry fails to converge.
Neither is a validity check on the base position — there is no plausibility
test at all, which is why the small-error band passes untouched.

## End-to-end through the real-time server

`e2e.sh` carries the attack the whole way: RINEX is encoded to RTCM3
(`rnx2rtcm3.c`), a malicious 1033 is spliced into the base correction stream
after every 1005 (`inject_1033.py`), and both streams are replayed into
RTKLIB's real-time server via `rtksvrstart` (`e2e_harness.c`). Nothing is
patched into the struct by hand.

```
### fortified build (-D_FORTIFY_SOURCE=2)
  clean          rc=0    final base position: -3978242.4348 3382841.1715 3649902.7667
  benign 1033    rc=0    final base position: -3978242.4348 3382841.1715 3649902.7667
  attack 1033    rc=134  *** aborted, no output ***

### unfortified build (-U_FORTIFY_SOURCE)
  clean          rc=0    final base position: -3978242.4348 3382841.1715 3649902.7667
  benign 1033    rc=0    final base position: -3978242.4348 3382841.1715 3649902.7667
  attack 1033    rc=0    final base position: -3978240.0000 3382841.1715 3649902.7667

base station truth:                           -3978242.4348 3382841.1715 3649902.7667
```

The unfortified row is the whole attack in one line: a base station silently
relocated **2.4 m** by a correction message, inside the real server, with the
receiver none the wiser. A benign 1033 of ordinary length changes nothing, so
the effect is the oversized length and not the injection itself.

`rc=134` is SIGABRT. Under ASan with `handle_abort=1` the fortified crash
resolves to:

```
*** buffer overflow detected ***
  #6 __strncpy_chk
  #7 strncpy  /usr/include/x86_64-linux-gnu/bits/string_fortified.h:106
  #8 decode_type1033  src/rtcm3.c:1019
  #9 decode_rtcm3     src/rtcm3.c:2579
  #10 input_rtcm3     src/rtcm.c:287
  #11 decoderaw       src/rtksvr.c:361
  #12 rtksvrthread    src/rtksvr.c:611
```

Note it is *glibc*, not ASan, that catches this. ASan itself stays silent
throughout, because the overflow never leaves the enclosing `rtcm_t`.

### What the abort does to the aircraft — measured

The abort is measured to the process boundary above: exit 134 (SIGABRT), stack
in `rtksvrthread` via `decoderaw`. `__chk_fail` calls `abort()`, which
terminates the whole process rather than the decoding thread, so `rtkrcv` stops
entirely — rover observation processing included, not just base decoding.

The question that matters is what the *consumer* does about that. Measured
2026-07-31 by running the closed loop in both columns, same `n1=211`, same
flight profile, same base siting:

    FORTIFY=1 HOLD=1 ./loop_demo.sh 211      # abort column
    HOLD=1 ./loop_demo.sh 211                # silent column (control)

**Read the harness note below first** — the naive version of this run measures
the simulator, not the aircraft.

#### Fortified: the vehicle notices in four seconds and puts itself down

| t (log) | event |
|---|---|
| 48.6 s | armed, GUIDED, GPS `Status=6` (RTK FIXED) |
| ~85 s | malicious 1033 spliced into the correction stream (*inferred* from the profile — the relay logs frame counts, not timestamps; the control run's parser puts the equivalent moment at 84.5 s) |
| 87.5 s | **last GPS record. `Status` 6 → 0.** `*** buffer overflow detected ***`, SIGABRT, core dumped |
| 91.4 s | `EKF3 lane switch 1`; `ERR EKF_PRIMARY ECode=1` |
| 91.5 s | `ERR EKFCHECK ECode=2` → `EKF variance` → `ERR FAILSAFE_EKFINAV ECode=1` → **`MODE LAND (rsn 6)`**, `EKF Failsafe: changed to Land Mode` |
| 98.6 s | `EKF3 IMU0 stopped aiding`, `IMU1 stopped aiding` |
| 105.9 s | `SmartRTL deactivated: bad position` |
| 120.6 s | `SIM Hit ground at 0.500060 m/s` |
| 122.7 s | `Disarming motors` |

**4.0 s from GPS loss to failsafe. 33.1 s from GPS loss to the ground**, at
0.50 m/s — a normal landing rate, not a crash. The aircraft abandoned the
commanded leg after flying 10.24 m of 29.93 m, which is the failsafe taking the
vehicle away from the waypoint, not an attacker walking it off course.

#### Unfortified control: nothing happens at all

Same injection, same profile, same aircraft:

| | fortified | unfortified |
|---|---|---|
| GPS `Status` | 6 → **0** at 87.5 s | **6 for the entire flight**, 49.2 → 188.2 s |
| `ERR` records | 4 | **0** |
| failsafes | EKF variance → LAND | **none** |
| mode changes | auto → LAND at 91.5 s | only the commanded LAND at the end of the profile |
| outcome | on the ground, disarmed, 33 s after GPS loss | flew the leg, reported arrival, **1.42 m from truth** |

That is the whole argument in one table, and it is the reverse of the intuitive
reading of the two columns. The build that *aborts* gives the vehicle a
detectable event and a policy to run. The build that ships gives it a confident
wrong answer and nothing to trigger on.

Autonomy stacks are built for "the sensor went away" — it is a declared state
with a failsafe attached, and here it fired in four seconds. Nothing is built
for "the sensor is confidently wrong", because there is no signal to fire on:
zero `ERR` records, zero mode changes, `Status=6` throughout.

**So on detectability the hardened build wins outright, and it is the one nobody
ships.** That is the finding. It is *not* a reason to call fortification a fix —
see the next section, which is the other half of this result.

### The abort is a second attack: an attacker-timed forced landing

The section above is about *detection*, and on that axis the fortified build
wins outright. It does not follow that the fortified build is safe, and reading
it that way misses an attack.

`SmartRTL deactivated: bad position` is the tell. With no position estimate the
aircraft **cannot** return home. Land-where-you-are is not one option among
several, it is the only one available — so **one packet, sent at a moment of the
attacker's choosing, puts the aircraft on the ground near wherever it happened
to be.** That is a denial-of-flight primitive with attacker-controlled timing,
and it is a capability the unfortified build does not offer.

"Near" is the whole question. Measured with `land_drift.py` on the same run:

| | |
|---|---|
| altitude at failsafe | 14.99 m AGL |
| descent time | 29.1 s at 0.52 m/s |
| **horizontal dispersion, GPS loss → touchdown** | **10.13 m** |
| dispersion, failsafe → touchdown | 9.42 m |
| character of the drift | monotonic — max excursion *is* the touchdown point |

With no horizontal position hold the aircraft slides for the whole descent, and
it does not wander back. So the attacker selects a **circle of tens of metres**,
not a point.

**That 10 m is a floor, not an expected value.** SITL's default is zero wind,
this was a low hover, and the aircraft had little residual velocity when the
failsafe fired. Wind, altitude, or a vehicle moving when it is hit all increase
dispersion — a longer descent is more time to drift.

What that buys an attacker who can see the target:

- **Works:** a lake, a river, a field of crops, a construction site, the far
  side of a perimeter fence. Anything where tens of metres of error is still
  inside the target.
- **Does not work:** a specific lane of traffic, a particular rooftop, a chosen
  vehicle. The dispersion is larger than the target.
- **Defeated by a human:** the aircraft is still flyable in non-GPS modes and
  the operator gets alarms. This is a live-pilot-recoverable attack and an
  unrecoverable one for an autonomous BVLOS flight.

#### Two attacks, not one bug and one mitigation

The two build columns hand an attacker **different weapons**. Neither is the
benign case:

| | unfortified (ships) | fortified (compile it yourself) |
|---|---|---|
| effect | position error | forced landing |
| precision | exact, chosen magnitude | ±10 m and up |
| magnitude | bounded — the usable band is ~0.4–2.5 m before the solution degrades | total: the aircraft stops flying |
| visible? | **no** — Q=1, zero `ERR`, nothing logged | yes — 4 `ERR` records, failsafe, alarms |
| timing control | yes | yes |
| best against | survey data, precision agriculture, landing accuracy, anything where 2 m matters and nobody checks | availability — taking an aircraft out of the air at a chosen moment |

The uncomfortable consequence, stated plainly: **for the goal of putting an
aircraft in the water, the hardened build is the more effective attack tool.**
Two metres of silent error will not do it; a forced landing will. Hardening
converts a silent integrity attack into a loud availability attack. That is a
real improvement in *detectability* and it is not an improvement in *outcome* —
the two are not the same thing, and the earlier framing in this repo treated
them as if they were.

So: report the detection result as the headline, because it is the surprising
one and it holds. Do not report fortification as a fix. The fix is the clamp
under "The fix"; fortification only changes which attack you are exposed to.

#### Still not measured

- **The crash loop on restart.** The attacker still controls the stream, and
  `inject_1033.py` splices a 1033 after every 1005, so a restarted process
  should walk into the next one and die again. Reasoned, not measured — the run
  above ends with the aircraft on the ground.
- **Dispersion as a distribution.** One run, one altitude, no wind. The 10.13 m
  is a single sample, not a mean or a bound. A dispersion claim worth quoting
  needs repeats across altitudes and wind settings.

#### Harness note: why `HOLD=1` exists, and what the naive run measures

The first attempt at this pointed SITL's GPS serial port straight at RTKLIB's
TCP server, and produced a result that looks like an answer and is not one.
RTKLIB aborts, the socket **closes**, and SITL's `tcpclient` port fails:

```
Closed connection on SERIAL3
connect failed on port 5903 - Connection refused at 88242 retrying
connect failed on port 5903 - Bad file descriptor
```

SITL then exits — the ~11-retry behaviour already noted in `loop_demo.sh`. The
flight driver dies with `ConnectionResetError`, the log ends at 88.1 s, and
**ArduPilot's failsafe logic never runs at all**. The simulator quitting is not
the aircraft's response.

It is also not what the failure looks like in the field. A receiver that crashes
on a UART does not take the serial line down with it; the wires stay up and the
bytes stop. `nmea_hold.py` reproduces that — it forwards normally, and when the
producer dies it holds the client socket open and sends nothing:

```
12:15:21 UPSTREAM GONE after 136429 bytes -- holding the client socket open, sending nothing
```

With the proxy in place SITL logs no port error at all and the flight runs to
completion. The proxy is proven transparent by the unfortified control run,
which reproduces the known result through it unchanged (1.42 m here against the
1.40 m recorded on 2026-07-27, base delta 1.800 m both times).

### What the receiver actually does about it

Running the unfortified build to completion on both streams and comparing
every solution epoch:

| | clean | attack |
|---|---|---|
| solutions emitted | 85 | 85 |
| Q=1 (RTK fixed) epochs | 17 | 17 |
| Q=2 (float) epochs | 68 | 68 |
| quality flag differs at any common epoch | — | **no** |
| 3D position shift vs. clean (82 common epochs) | — | min 2.432 m, mean 2.433 m, **max 2.435 m** |

The injected base-position error was **2.435 m**. The rover's reported position
moves by that amount, one-for-one, and **the quality flags are identical** —
same count of fixed epochs, same flag at every single epoch. No dropouts, no
degradation, no rejection.

So the answer to "what does the receiver do about it" is: **nothing**. It does
not notice. It emits a position 2.4 m from truth while reporting exactly the
confidence it reports when everything is correct.

### What an operator could see, with tracing fully enabled

"Nothing is logged" is close but not exact, and the exact version is better.
RTKLIB does have a trace facility, and the 1033 decoder does write to it. Read
at `rtcm3.c` and `rtksvr.c`, three things are true.

**The success path emits one line, at level 3:**

```c
trace(3,"rtcm3 1033: ant=%s:%s rec=%s:%s:%s\n",des,sno,rec,ver,rsn);
```

**That line cannot show the attack.** It prints the *staging buffers*, not the
wire fields — and the read loops that fill them are bounded at `j<n1&&j<31`. So
the log shows at most the first 31 characters of the receiver-type field, which
the attacker chooses and can make read like an ordinary descriptor. A message
declaring `n1=255` produces a trace line indistinguishable from a benign one.
**The declared length never appears in any log output at any level.** The only
other thing written is the station id, via the `rtcm->outtype` branch:
`sprintf(msg," staid=%4d",staid)`.

**The damaging step is not traced at all.** `update_antpos()` (`rtksvr.c:251`),
which copies the corrupted coordinate into `svr->rtk.rb`, contains no trace call
— the whole function is quoted under "Why this is a positioning bug" above, and
a grep of `rtksvr.c` finds nothing logging `rb` on this path. The only record
that a base position was adopted at all is a counter increment,
`svr->nmsg[index][4]++`.

There is a level-2 trace, `rtcm3 1033 length error: len=%d`, but it fires only
when the declared field lengths exceed the frame — `i+60+8*(n+m+n1+n2+n3) <=
rtcm->len*8`. The attack frame is internally consistent (it really does carry
255 bytes of receiver-type data; the decoder simply copies only 31 of them into
a buffer and then writes `n1` bytes out of it), so this never fires.

Two further gates before any of the above is even reachable: trace output is
compiled out entirely unless `TRACE` is defined (`rtkcmn.c:3023` — otherwise
`trace()` is an empty stub), and `level_trace` initialises to 0 against a guard
of `if (!fp_trace||level>level_trace) return`. The trace strings *are* present
in the shipped Windows binaries and in Debian's armhf `rtkrcv` (see above), so
those builds have it compiled in — but an operator would still have to open a
trace file and explicitly raise the level to 3.

**The accurate claim, then:** at default settings nothing is written. With
tracing compiled in and turned all the way up, an operator gets one line
recording a plausible-looking antenna descriptor, and **still no record that the
base station's coordinates changed**. The instrumentation exists and watches the
wrong thing.

### Over a serial link

`e2e_serial.sh` delivers the identical attack over a pseudo-terminal instead of
a file, so the bytes arrive on a real tty — the transport a UHF/VHF correction
radio presents to a rover. No RF is transmitted.

```
### over a pty (serial transport)
  unfortified, clean       rc=0    final base position: -3978242.4348 3382841.1715 3649902.7667
  unfortified, attack      rc=0    final base position: -3978240.0000 3382841.1715 3649902.7667
  fortified, attack        rc=134  *** aborted, no output ***

base station truth:                -3978242.4348 3382841.1715 3649902.7667
```

Byte-for-byte the same outcome as the file transport. This is expected from the
code — `strread()` is a pure demux over `STR_SERIAL`/`STR_FILE`/`STR_TCPCLI`/
`STR_NTRIPCLI`/`STR_UDPSVR` into one buffer, and `rtksvrthread` then calls
`decoderaw()` → `input_rtcm3()` identically — but it is now measured across two
genuinely different transports rather than argued from the source.

Note RTKLIB builds its device path as `sprintf(dev,"/dev/%s",port)`, so a pty
linked under `/tmp` is addressed as `../tmp/ttyBase`. That traversal is a
convenience for this harness, not part of the attack.

**Payload size.** The complete attack is a single frame:

| | |
|---|---|
| minimal 1033 frame (no antenna descriptor) | **227 bytes** |
| airtime @ 9600 bps | 0.24 s |
| airtime @ 4800 bps | 0.47 s |
| RTCM3 maximum frame | 1029 bytes |

Comparable to a routine MSM7 or multi-satellite 1004 message, so it is
unremarkable traffic on a link already carrying corrections.

**What a radio delivery would still require, none of it verified here:**

- The link must actually carry RTCM3. Many RTK UHF links run Trimble
  CMR/CMR+/CMRx, Satel or other proprietary formats; RTKLIB decodes CMR through
  a different path with no type 1033, so the bug is not reachable there.
- Transparent-serial radios pass bytes through unchanged; radios that
  packetize, scramble or apply their own FEC may not.
- The rover's receiver must lock onto the injected frames. The attack is
  *additive* — an extra message in the gaps — so the legitimate base does not
  need to be suppressed or its stream rewritten.
- Persistence differs by build. A fortified target dies on the first frame, so
  one transmission suffices. On an unfortified target the next legitimate 1005
  rewrites `sta.pos` and restores truth, so the corruption must be re-injected
  after every 1005 to hold — continuous transmission, not one shot.

### What a vehicle does with it

`sitl_demo.sh` flies the measured offset on ArduPilot (official prebuilt
ArduCopter 4.7.0 SITL). The attack is applied through `SIM_GPS1_GLTCH_X/Y`,
which SITL adds directly to the reported latitude/longitude in degrees — the
same effect a corrupted base-station coordinate has on an RTK solution.

```
injected GPS offset : N=+1.07 m  E=-1.58 m  |1.91 m|
true position moved : N=-1.07 m  E=+1.57 m  |1.90 m|   (residual 0.01 m)

navigating to a commanded waypoint
  commanded    : 35.161145791, 139.613834769
  actually at  : 35.161136266, 139.613851724
  MISS DISTANCE: |1.87 m|      (flew 29.96 m of a 31.06 m leg)
```

Two results:

- **Holding position**, the aircraft physically moved **1.90 m — exactly
  opposite the injected offset**, residual 0.01 m. It repositioned to correct
  a drift that never happened.
- **Navigating to a waypoint**, it flew the leg and stopped **1.87 m from
  where it was told to go, reporting that it had arrived.**

Ground truth is read from the simulator's dataflash log (`parse_sitl_log.py`),
not from streamed telemetry. Two earlier results from this harness were
**wrong** and are worth recording as traps:

1. Streaming `SIMSTATE` over MAVLink while also transmitting GPS from another
   thread corrupted the link; the truth feed stalled and a frozen ground truth
   is indistinguishable from an aircraft holding perfectly still.
2. Holding in `LOITER` looked like "the aircraft absorbed the attack". It had
   not: `LOITER` is pilot-controlled, and with no RC transmitter attached in
   SITL the throttle reads zero, so the aircraft descended and **disarmed 7
   seconds before the attack was applied**. The demo holds in `GUIDED`, which
   is autonomous, for exactly this reason.

The parser refuses to report a waypoint miss unless the aircraft actually flew
the leg, because a vehicle that never moved shows a "miss" equal to the whole
leg length.

### Driving an autopilot from RTKLIB's own output

The vehicle result above feeds ArduPilot an offset directly. The join that
would remove that seam is to make RTKLIB the autopilot's actual GPS, and the
interface for it works:

`NMEA_OUT=<path> ./e2e_nmea ...` makes the harness emit the solution as NMEA
(RMC + GGA + GSA + GSV). The attack survives the format conversion intact:

```
clean   $GNGGA,235942.00,3509.6524895,N,13936.8299504,E,5,07,...
attack  $GNGGA,235942.00,3509.6530663,N,13936.8289113,E,5,07,...
                          ^^^ position moves      quality unchanged ^

delta N=+1.070 m  E=-1.576 m  |1.905 m|      115 GGA sentences in both runs
```

`nmea_bridge.py` feeds that into a pty, and ArduPilot reads it as an ordinary
GPS (`GPS_TYPE=5`, `--serial3 uart:/tmp/ttyNMEA`):

```
gps: fix=5 (RTK float) sats=6 lat=35.1608751 lon=139.6138377
EKF3 IMU0/IMU1 is using GPS
ekf: flags=0x033f
```

So RTKLIB can drive the vehicle, and the position error and the quality flag
both reach the consumer unchanged. Nothing in the autopilot knows RTKLIB is
involved.

**What still prevents a single packet-to-propeller chain.** RTKLIB needs rover
*observations* from wherever the vehicle actually is, and the test data is a
stationary ground station. Two ways to close it:

- *All software:* synthesise the rover's observables from the base's plus the
  geometric difference — `rover_P(sat) = base_P(sat) + (|sat−rover| −
  |sat−base|)`. Every real error source is inherited from the base and cancels
  exactly in double-differencing, so RTK resolves cleanly and the true
  baseline is exactly `rover − base`. Needs care over feedback stability,
  since the autopilot then steers the vehicle whose position feeds the GPS
  that steers the autopilot.
- *Hardware:* a real u-blox F9P under open sky removes the problem entirely —
  real satellites produce real observables for wherever the receiver actually
  is. Corrections arrive over NTRIP or a 433/915 MHz radio link, and the
  injection is the same additive splice `inject_1033.py` already performs.
  No RF transmission is required for the NTRIP variant.

The quality field reads 5 (RTK float) rather than 4 (fixed) because
`rnx2rtcm3` loses some phase precision in re-encoding. Clean and attacked runs
are identical in every flag, so the comparison holds, but "still reports
FIXED" is demonstrated on RINEX input, not through this bridge.

### Synthetic observables: driving RTKLIB from an arbitrary rover position

`gnss_sim.c` generates the observables two receivers at two known positions
would produce, and encodes both as RTCM3. It exists so RTKLIB can be driven
from a rover position we choose — ultimately a *moving* one — rather than only
from the fixed ground station in the bundled test data.

Both receivers' observables come from the same model at the same epoch:

```
P = |sat − rx| − c·dts        L = P / λ
```

Everything common to the two receivers cancels exactly when RTKLIB forms
double differences, so DD residuals are zero by construction and ambiguity
resolution is trivial. This is not a realistic signal simulator — no
atmosphere, no multipath, no clock drift — and does not need to be. The
quantity under test is what RTKLIB does with a corrupted *base coordinate*;
the observables only have to be self-consistent.

Validated against a 10 m baseline:

| | latitude | longitude | height |
|---|---|---|---|
| RTKLIB solved | 35.132156283 | 139.624302129 | 75.7905 |
| true rover | 35.132156276 | 139.624302130 | 75.8027 |
| error | 0.8 mm | 0.1 mm | 1.2 cm |

**Q=1 (RTK fixed)**, sub-millimetre horizontally. Injecting the 1033 into the
synthetic base stream then gives:

```
clean   35.132156283  139.624302129  75.7905   Q=1   rb = -3978242.4348 ...
attack  35.132165903  139.624284824  74.2748   Q=1   rb = -3978240.0000 ...

shift: N=+1.071 m  E=-1.575 m  U=-1.516 m   3D = 2.434 m
injected base error:                              2.435 m
```

One-for-one propagation, and **Q=1 fixed in both runs**. This supersedes the
earlier caveat that "still reports FIXED" was only demonstrated on RINEX
input: on synthetic observables the solution holds a fixed ambiguity
throughout, clean and attacked alike.

### The loop closed: packet to propeller in one run

`loop_demo.sh` joins the halves. The aircraft's own position becomes the
observables RTKLIB solves, and RTKLIB's solution is the aircraft's only GPS:

```
SITL truth --> gnss_sim --> [relay splices the malicious 1033]
                                   |
                             RTKLIB (rtksvr)
                                   |
                                 NMEA
                                   |
                            SITL's GPS --> vehicle moves
```

Nothing is fed in by hand. The offset reaches the flight controller only as one
extra well-formed message on the correction link, spliced on-path into a live
TCP stream by `inject_relay.py` after every 1005.

A control run with injection disabled (`./loop_demo.sh 0`) is what makes the
attacked run readable, and it is not optional — see the harness defects below.

Both runs below use a **stock ArduPilot parameter set** — the only parameters
the demo sets are the ones that wire the harness up (frame class, GPS type,
serial protocol, stream rates). No tuning or estimator parameter is changed.

| | control, 0 injected | attacked, 520 injected |
|---|---|---|
| GPS vs. truth, before | 0.00 m | 0.01 m |
| GPS vs. truth, after | 0.00 m | **1.92 m** |
| displacement while holding in GUIDED | — | **1.86 m**, opposite the offset |
| commanded-waypoint miss | **0.04 m** | **1.86 m** |
| distance flown on the leg | 29.99 m of 29.95 m | 29.38 m of 30.40 m |

Clean, the aircraft flies to within **4 cm** of the coordinate it was given.
Attacked, it stops **1.86 m** away and reports that it has arrived, having
flown essentially the whole leg.

Those figures agree with the separately measured open-loop ones, and not only
in magnitude — component by component, to within 5 cm:

| | injected offset | aircraft moved | waypoint miss |
|---|---|---|---|
| open loop (`sitl_demo.sh`) | N +1.07  E −1.58 | N −1.07  E +1.57 | N −1.06  E +1.54 |
| closed loop (`loop_demo.sh`) | N +1.06  E −1.58 | N −1.05  E +1.54 | N −1.03  E +1.55 |

Two independent paths to the same vector: one that hands the autopilot a
position error directly, one that makes it compute that error itself from a
corrupted correction message. In both, the aircraft's physical displacement is
**opposite** the injected offset (residual 0.01 m and 0.04 m respectively) —
it repositions to correct a drift that never happened.

That pair of runs is retained as the cross-validation, because agreeing
component by component across two different methods is what makes either of
them believable. **It is not the configuration the demo now runs**, for the
reason below.

#### The demo runs at `n1=211`, on a base sited to make it visible

The runs above use `n1=212`, whose 512 m quantum happened to land on 2.435 m
against that base. `n1=211` is the length that generalises — a 2 m quantum,
so bounded error against *any* base station — but against `-3978242.4348` it
produces 0.43 m, which is correct, universal, and invisible from the back of a
room.

Both problems go away by siting the base, which is free here because the base
coordinate is ours to choose: `-3978243.8000` sits 1.80 m above the 2 m lattice
point, so the reliable rung produces a visible error. Deliberately *not*
`-3978243.9998`, which would maximise it at 1.9998 m but sit 0.2 mm from the
boundary, where any sub-millimetre shift in the encode/decode path collapses the
effect to ~0 and the demo silently shows nothing.

**Say the quiet part on the slide:** the site was chosen so the error lands near
the top of its range. At an arbitrary real base the `n1=211` error is uniform in
`[0, 2) m` with a mean of 1 m. The *guarantee* is the bound, not the 1.8.

Measured, stock parameters, control first:

| | control, 0 injected | attacked, 520 injected |
|---|---|---|
| GPS vs. truth, before | 0.00 m | 0.00 m |
| GPS vs. truth, after | 0.00 m (sustained max 0.06 m) | **1.45 m** |
| injected offset | — | N +0.78  E −1.17  \|1.41 m\| |
| displacement while holding in GUIDED | — | N −0.78  E +1.12  **\|1.36 m\|, opposite** (residual **0.05 m**) |
| commanded-waypoint miss | **0.03 m** | **1.39 m** |
| distance flown on the leg | 29.94 m of 29.91 m | 29.60 m of 30.33 m |
| clean flight before the attack | — | airborne t=53.7 s, attack t=85.0 s (**31 s**) |

The control lands within **3 cm** — better than the 4 cm the previous base gave,
so nothing about the new siting hurt the harness. The horizontal figure was
predicted at 1.42 m before the run, from the 1.80 m ECEF error scaled by the
previously measured 2.435 → 1.92 ratio; it measured **1.41 m**. That agreement
is worth more than the number itself: it means the bit-level truncation model,
the ECEF-to-local geometry, and the vehicle response compose predictably.

The cost of the change is 0.5 m of drama. What it buys is that nothing in the
demo depends on a coincidence: **1.8 m here, under 2 m everywhere, no knowledge
of the base coordinates required.**

#### The vertical third of the error does nothing, and that is the interesting part

1.80 m of ECEF error against 1.41 m horizontal leaves ~1.1 m in height.
`parse_sitl_log.py` now measures it, separately from the horizontal and never
folded into it, because the autopilot weighs the two completely differently.

| | control | attacked |
|---|---|---|
| vertical GPS-vs-truth, t=65–84 s | −36.320 m | −36.321 m |
| vertical GPS-vs-truth, t=90–115 s | −36.320 m | −37.440 m |
| **step** | **0.000 m** (σ 0.005 m) | **−1.120 m** |
| aircraft's true height change | — | **−0.04 m** |

The constant −36.32 m is a datum difference between `GPS.Alt` and `SIM.Alt`,
identical in both runs and irrelevant — the step is what matters, and the
control's is zero to three decimal places, so the 1.12 m is the attack.

It was also **predicted before it was measured**: √(1.80² − 1.41²) = 1.12 m.
That is now the third independent confirmation that the truncation model, the
ECEF-to-local geometry and the measured response compose correctly.

**The aircraft ignored it.** 0.04 m of true height change against a 1.12 m lie
— a 3% response, against the horizontal's ~97%. The reason is not subtle:
ArduPilot's EKF3 takes height from the **barometer** by default
(`EK3_SRC1_POSZ`), so a corrupted GPS height is outvoted by a sensor the
attacker never touched. Horizontally there is no second opinion — nothing else
on the airframe knows where it is — so the lie goes through unopposed.

That is worth stating plainly rather than burying, for two reasons. It **bounds
the attack honestly**: roughly a third of the injected error is wasted, and the
effect is horizontal-only on a multirotor configured this way. And it points
straight at the defence: the axis with a redundant, independent sensor resisted;
the axis without one moved. Nothing about this is specific to barometers.

A corollary for anyone extending this: a vehicle that *does* fuse GPS height —
a fixed-wing without a reliable baro reference, or any configuration with
`EK3_SRC1_POSZ` set to GPS — should be expected to move in all three axes. That
is untested here.

**Three harness defects had to be fixed first, and all three produced results
that looked like attack effects.**

*Altitude fed back as truth.* `mav_pos.py` initially read
`GLOBAL_POSITION_INT` altitude — the vehicle's own estimate — and fed it back
as the rover's position, so the estimate defined the observables that then
confirmed it. Solution height ran from 75.8 m to −143 m in 40 s. Truth
altitude comes from `SIM_STATE` now, which belongs to no stream group and has
to be requested by message id.

*A GPS insisting the aircraft was stationary.* RTKLIB's NMEA RMC reports a
speed of 0.00 regardless of how fast the rover moves — measured against a
rover fed a known 1 m/s ramp, and `prcopt.dynamics` does not change it, so the
solution simply carries no velocity to format. `GPS.Spd` was 0.000 in all 496
dataflash records of a flight covering 124 m. ArduPilot's EKF3 fuses GPS
velocity by default, and the result was an oscillation that doubled in
amplitude every ~9 s until the aircraft wandered 113 m off. It looked like a
dramatic attack effect. It was not: **a control run with no injection at all
drifted 25.9 m and missed its waypoint by 45.4 m.**

The first fix was `EK3_SRC1_VELXY 0`, which stops the EKF using GPS velocity at
all. That worked, but it is a deviation from a stock configuration forced by
the harness rather than by the attack, and a demo is weaker for every parameter
it has to explain away. **It is no longer used.** Instead the harness supplies
the velocity RTKLIB does not: `NMEA_VEL=1` makes `e2e_harness.c` format the
NMEA itself, deriving the velocity by differencing successive solutions at
5 Hz. Be plain that **differencing stands in for the Doppler velocity a real
receiver measures** — it is noisier, and unlike Doppler it responds to a step
in the position solution, so a median of three samples rejects the one-epoch
~12 m/s spike the moment the base coordinate jumps.

One further thing had to change with it. RTKLIB's `outnmea_rmc()` reports the
*previous* course whenever speed is below 1 m/s (`static double dirp`, which
starts at 0.0), so a correct speed still arrives with a frozen bearing.
Measured with no vehicle in the loop: fed 0.5 m/s due east, RTKLIB's RMC
reports 0.499 m/s on a course of 0.0° — a 90° error. ArduPilot rebuilds
velocity as speed × course, and a hovering multirotor lives entirely in the
sub-1 m/s band, so this is a *consistent* error the estimator integrates rather
than noise it averages away. With it, the aircraft oscillated ±3 m while
holding; the waypoint leg, flown above 1 m/s where the course is live, was
unaffected. `own_rmc()` formats the sentence with the course computed at every
speed — same fields, same talker id, and GGA/GSA/GSV still RTKLIB's own.

`MODE=speed ./loop_latency.sh` checks this without a vehicle: fed 0.5 m/s on a
bearing of 90°, the RMC now reports 0.499 m/s and 90.0°; fed 0.3 m/s on 225°,
0.298 m/s and 225.1°. The control run then lands within **4 cm** on stock
parameters, which is better than the 9 cm the workaround achieved.

*An attack that began before the aircraft did.* The relay armed itself on a
timer counted from the moment RTKLIB connected to it, which put it downstream
of every startup delay in the chain. It lost the race: the GPS started lying at
t=44.2 s, the aircraft armed at t=43.1 s and did not leave the ground until
t=47.4 s. There was no clean flight phase at all, and the GUIDED hold target —
read from the vehicle's own reported position once airborne — was captured from
a position the GPS was already falsifying. The displacement measured against
that target was a takeoff transient anchored to the lie, and it carried the
same sign as the offset, which is why the closed and open loops appeared to
disagree about direction. They do not; the earlier run was simply not measuring
a response to anything. The relay now waits for a trigger file that
`ardupilot_demo.py` creates when it is airborne and holding, so the aircraft
decides when the clean phase ends and no clock is involved. `parse_sitl_log.py`
independently checks the attack against the takeoff time and refuses to report
a displacement if the ordering is wrong.

Loop delay was measured and exonerated on the way: `loop_latency.sh` puts a
square wave through the whole chain with no vehicle in it and times the edges,
giving **130 ms**, consistent to ±10 ms, which is faster than a real GPS and
well inside what the EKF expects.

### Why the dataset is time-shifted

RTCM3 type 1019 carries only a 10-bit GPS week, so the decoder resolves the
1024-week rollover against the current date. Replaying the 2005 test data
today lands the ephemeris ~20 years out and every satellite position is
garbage. `rnx2rtcm3` shifts the whole dataset by a whole number of GPS weeks
(`SHIFT_WEEKS`, default 1024) into the present rollover window, preserving
every time difference the positioning math depends on. This is an artifact of
replaying old data, unrelated to the vulnerability.

**AddressSanitizer reports nothing for any of the three runs**, including
`oob.bin`, which genuinely writes past the end of `recsno[64]`. Both the source
and destination are members of the same allocation, so no redzone is crossed.

This is **not** a new observation — FuzzingLabs documented it in the issue
report and it is why they used UBSan rather than ASan:

> `rtcm->sta` is embedded in the large `rtcm_t` object, so the overflow stays
> *within* that single allocation. AddressSanitizer (which checks allocation
> boundaries) does not flag it, while UBSAN's `array-bounds` check — which
> knows the declared `char[64]` field bound — catches it precisely.

Their reproduction gets `runtime error: index 255 out of bounds for type
'char[64]'` under UBSan. The measurements here reproduce that independently
with a different toolchain (gcc/glibc vs. Apple clang).

## Files

| file | purpose |
|---|---|
| `gen_rtcm.py` | builds valid RTCM3 1005 and 1033 frames (CRC24Q, correct length) |
| `harness.c` | feeds a byte stream into unmodified `input_rtcm3`, dumps `sta` |
| `build.sh` | compiles the harness against an RTKLIB checkout (`ASAN=1` optional) |
| `run.sh` | regenerates all three streams and runs them |
| `downstream.sh` | length sweep + effect of each magnitude on the RTK solution |
| `rnx2rtcm3.c` | encodes a RINEX obs/nav pair into a replayable RTCM3 stream (+time tags) |
| `inject_1033.py` | splices a malicious 1033 into an existing stream, remapping time tags |
| `e2e_harness.c` | drives RTKLIB's real-time server (`rtksvrstart`) on those streams |
| `e2e.sh` | the whole end-to-end run, fortified and unfortified |
| `serial_feed.py` | feeds the streams into ptys so RTKLIB receives them over a UART |
| `e2e_serial.sh` | the same end-to-end run delivered over serial |
| `ardupilot_demo.py` | flies the measured offset on an ArduPilot vehicle |
| `parse_sitl_log.py` | measures the aircraft response from the dataflash log |
| `sitl_demo.sh` | runs the flight and the analysis together |
| `nmea_bridge.py` | feeds RTKLIB's NMEA solution to an autopilot as a GPS |
| `gnss_sim.c` | synthesises base+rover observables for two arbitrary positions |
| `inject_relay.py` | on-path relay: splices the 1033 into a live stream, after every 1005 |
| `mav_pos.py` | streams the simulated vehicle's ground truth to `gnss_sim` |
| `loop_demo.sh` | the closed loop — packet to propeller in one run (`0` for the control). `FORTIFY=1` builds the abort column; `HOLD=1` inserts the keep-alive proxy that run requires |
| `nmea_hold.py` | keeps the NMEA link up after RTKLIB dies, so the fortified run measures the aircraft's failsafe rather than SITL quitting on a closed port |
| `land_drift.py` | the forced-landing attack: time to failsafe, descent, and the horizontal dispersion between GPS loss and touchdown — the attacker's targeting error. Refuses a log with no failsafe in it |
| `loop_latency.py` / `.sh` | loop delay with no vehicle in it; `MODE=speed` checks the reported ground speed and course against a fed ramp |
| `sign_check.py` | truth, GPS and EKF traces in one frame — which way the aircraft moved, and why |
| `misalign_check.py` | the second defect: a declared length above 31 misaligns every field parsed after it, with a control at 20 |
| `check_1007_1008.py` | does the same unclamped-`strncpy` shape in `decode_type1007`/`1008` reach `sta.pos` — measured negative: `antdes`/`antsno` sit too early in `sta_t` to reach it or to leave the struct |
| `check_clamp.sh` | does the proposed fix work — stock vs. clamped on the same streams, plus UBSan with the control firing first |
| `check_fork.sh` | is a given RTKLIB fork still vulnerable — unclamped copy, `offsetof(sta_t,pos)`, and whether the real-time path adopts the coordinate unguarded |
| `check_offsets.py` | does the payload length transfer to other architectures — `sta_t` layout across six ABIs, by cross-compilation, with nothing run on the target |
| `check_binary.sh` | which column a shipped binary falls into: `*_chk` imports, and whether the 1033 decoder is actually in the binary being tested |
| `check_image.sh` | look inside a firmware/OS image for RTKLIB without root — `dd` + `debugfs`, no mounting |
| `pick_base.py` | what each `n1` rung does to a given base coordinate, and where to site a demo base so the reliable rung is also a visible one |

```sh
git clone -b rtklib_2.4.3 https://github.com/tomojitakasu/RTKLIB
RTKLIB=./RTKLIB ./run.sh
RTKLIB=./RTKLIB ASAN=1 ./run.sh
```

**Reproducing the provenance claims.** The three "is it really in X" findings
are re-runnable rather than asserted:

```sh
./check_fork.sh emlid/RTKLIB reach          # the Reach fork: still vulnerable?
./check_fork.sh tomojitakasu/RTKLIB rtklib_2.4.3   # upstream, for comparison

curl -O http://deb.debian.org/debian/pool/main/r/rtklib/rtklib_2.4.3.b34+dfsg-1+b2_armhf.deb
./check_binary.sh rtklib_2.4.3.b34+dfsg-1+b2_armhf.deb   # fortified or not?

./check_image.sh some-firmware.img          # rootless: is RTKLIB in there?
./pick_base.py --explain -3978243.8000      # what each rung does to the demo base
```

`check_fork.sh` computes `offsetof(sta_t,pos)` from the fork's own header
rather than assuming it, because that offset is what decides whether the
payload lengths measured here transfer to that target unchanged. It prints the
number so it can be checked by hand against the 464 derived above.

`harness.c` reproduces the base-position adoption from `update_antpos()`
verbatim rather than linking the whole server; the copied block is marked and
cited in the source.

## Relationship to the FuzzingLabs disclosure

Reconciled against the [#799 issue body](https://github.com/tomojitakasu/RTKLIB/issues/799)
(Nabih Benazzouz / @Raefko, 2026-06-09) and the
[writeup](https://fuzzinglabs.com/breaking-rtklib-gps/).

**Theirs, and confirmed here.** The out-of-bounds write; ~191 bytes past a
64-byte field across five fields; the missing clamp with only a frame-length
guard; unauthenticated reachability via NTRIP/serial with a computable CRC;
containment within the single `rtcm_t` allocation; ASan blindness and the
need for UBSan; "corrupts adjacent `sta_t`/`rtcm_t` members". All of it holds.
Their report also notes the same unclamped pattern in `decode_type1007`
(`rtcm3.c:469`) and `decode_type1008` (`:507`) — now examined here, see
"`decode_type1007`/`1008`: same shape, measured to not reach `pos`" above:
same missing clamp, confirmed to stay within `sta_t` and short of `pos` at
any declared length, so memory-safety only on both. Those two line numbers
are quoted as they appear in their report and do not
resolve against the tree measured here, where the functions begin at 504 and
537 — presumably a different checkout on their side.

**Refined here.** The overflow content is NUL padding, not attacker bytes, so
there is no controlled write — which settles the exploitability question
negatively. Their report is careful to say attacker-controlled *length* and
never claims otherwise; it simply does not address the content.

**Not in their report.** Nothing in it mentions `sta.pos`, base-station
coordinates, or any effect on the position solution — the impact is framed
throughout as memory corruption. Specifically new here:

- `sta.pos` corruption is reachable. The *write* that causes it is still an
  out-of-bounds write on `rectype[64]`, so UBSan flags it exactly as
  FuzzingLabs reported — but the sanitiser reports a bounds violation, not
  that the station coordinates have been altered. Nothing about the
  positioning consequence is visible from the sanitiser output, and ASan is
  silent throughout because the overflow stays inside `rtcm_t`.
- Their PoC drives `n` (the `antdes` length), which maxes out at offset 383 and
  **cannot reach `pos` at 464**. Only `rectype`, `recver` and `recsno` can. For
  the same reason `decode_type1007`/`1008`, which write only the earlier
  fields, cannot reach it either — 1033 is the only one of the three that can
  (now measured, not just argued from offsets — see above).
- A second, unrelated defect in the same function: a declared length above 31
  misaligns every field parsed after it, because the sequential walk advances
  by at most 31 bytes while the wire format carries the full length. Not a
  memory-safety issue, and not what the station-position attack uses. See
  "A second defect" above.
- The declared length acts as a magnitude dial on the coordinate error.
- A small error leaves the solution at Q=1 (RTK fixed) while metres off.
- On glibc builds with `_FORTIFY_SOURCE` active, the fortified `strncpy`
  aborts the process — a remote DoS. They tested under Apple clang with
  sanitizers and no optimisation, where this does not arise.
- `update_antpos()` (`rtksvr.c:251`) adopts the corrupted coordinates into the
  baseline without validation, while the post-processing path guards with
  `norm()`.

In short: they found and correctly characterised the memory-safety defect. The
positioning-integrity consequence and the build-dependent split are additions.

## The fix

Five lines, placed after the frame-length check — which must keep using the
declared lengths, since it is the wire framing test — and after the read loops,
which already discard anything past 31:

```c
if (n >31) n =31;
if (m >31) m =31;
if (n1>31) n1=31;
if (n2>31) n2=31;
if (n3>31) n3=31;
```

The staging buffers are 32 bytes, so this only stops the write from claiming
more than was ever read. `check_clamp.sh` builds the harness against the stock
checkout and against a tree whose only difference is the clamp, and runs the
same streams through both:

| stream | stock `sta.pos` | clamped |
|---|---|---|
| benign | truth | truth |
| `n1=211` | -2694684.0000 (1.47 m off) | **truth** |
| `n1=255` | 0, 0, 0 | **truth** |
| `recsno=255` | 0, 0, 0 (and `dgps` cleared) | **truth** (`dgps` intact) |

And under UBSan, with the control firing first so that "clean" means something:

```
stock:   runtime error: index 255 out of bounds for type 'char [64]'   (rtcm3.c:1019)
clamped: clean
```

Benign streams decode byte-identically, so the clamp costs nothing a conforming
base station would notice.

**Not filed as a PR yet** — pending a response to the analysis posted on
issue #799 (2026-07-27). It does not fix the misalignment defect described
above; that one is in the walk, not the write.

## Disclosure status

RTKLIB issues #796-799 (FuzzingLabs, 2026-06-09) are all **open and
unpatched** as of 2026-07-25. #799 is the type 1033 bug. Each carries a single
comment from the reporter offering to file a GHSA and request a CVE, and
asking the maintainer how they would like to track it. There has been no
maintainer reply in seven weeks, and the release branch has had no commit
since December 2020.

The bugs are already public — GitHub issues plus a published writeup — so
presenting them is not a 0-day drop. But "wait for the patch" is not a viable
gate on an unmaintained project, and that is worth saying explicitly rather
than implying a fix is coming.

## Limitations

Read these before quoting anything above.

- **The vehicle results are simulations.** No real aircraft or GPS hardware was
  involved anywhere in this work. `sitl_demo.sh` feeds ArduPilot the measured
  offset through its GPS glitch parameters, so there the autopilot never sees
  the malicious RTCM3; that isolates the consequence of an offset of this size
  on a real control loop. `loop_demo.sh` closes the chain and does have the
  autopilot compute the error itself from the injected message.
- **The closed loop supplies its own GPS velocity**, because RTKLIB's rtksvr
  path reports none and ArduPilot's EKF3 fuses velocity by default. It is
  derived by differencing successive position solutions, which stands in for
  the Doppler velocity a real receiver measures: noisier, and unlike Doppler it
  responds to a step in the position solution. The estimator parameters are now
  stock (`EK3_SRC1_VELXY 0` is gone), but the *receiver* is doing something a
  real one would not have to.
- **The abort column is measured on ArduPilot SITL only, one vehicle, one
  profile.** See "What the abort does to the aircraft". The 4.0 s to failsafe
  and 33.1 s to ground are ArduCopter 4.7.0 with EKF3 and stock failsafe
  parameters; another airframe, another estimator, or a non-default
  `FS_EKF_ACTION` would give different numbers, and a fixed-wing or a ground
  vehicle would behave differently again. The *direction* of the result — an
  event the vehicle can act on, versus none — is the claim; the seconds are
  illustrative. The crash-loop behaviour on restart is reasoned, not measured.
- **The forced-landing dispersion is one sample.** 10.13 m, from a 15 m hover,
  in **zero wind**, on a vehicle that was nearly stationary when the failsafe
  fired. It is a floor and it is not a distribution: no repeats, no wind sweep,
  no altitude sweep. Say "about 10 m in the one run measured, and more in any
  real condition" — not "±10 m", which implies a bound that has not been
  established.
- **Fortification is not a fix and must not be reported as one.** It exchanges
  a silent position-corruption attack for a loud forced-landing attack. The fix
  is the clamp.
- **Read the control run before quoting any closed-loop number.** Three harness
  defects each produced large, attack-shaped displacements with no attack
  present. `./loop_demo.sh 0` is the check, and it should land within
  centimetres.
- Only a multirotor holding position and flying a short GUIDED leg was tested.
  Fixed-wing, autosteer, marine autopilots and survey workflows are untested,
  as is any behaviour under a gradually ramped offset rather than a step.
- The `rnx2rtkp` runs drive the post-processing entry point with explicit base
  coordinates, and are retained because they isolate the positioning maths and
  sweep magnitudes the live run does not. The live run is the authoritative
  one for the end-to-end claim.
- The RINEX-derived stream solves mostly at Q=2 (float) because `rnx2rtcm3`
  loses phase precision in re-encoding; clean and attacked runs share that
  encoding and produce identical flag sequences, so the comparison holds. The
  synthetic streams from `gnss_sim` do not have this problem and hold Q=1
  (fixed) in both runs.
- Offsets were originally x86-64 / gcc, and are now measured across six ABIs —
  x86-64, armhf, armel, arm64, riscv64, ppc64 — which all put `pos` at 464, so
  the thresholds transfer unchanged (`check_offsets.py`, and see "The payload
  length transfers unchanged"). The shipped 32-bit Windows build agrees, for
  the same reason: everything in `sta_t` ahead of `pos` is `char` arrays and
  `int`s. What is measured there is the **ABI**, via two compilers that agree —
  not any particular shipped binary. A build with non-default packing or a
  patched header would still need its own thresholds; none was found or looked
  for.
- The magnitude for a given `n1` is dataset-specific — it depends on the base
  station's coordinate values, since mantissa bytes are being truncated.
- Only one rover/base pair (2005, GPS-only) was tested. Whether the Q=1
  behaviour holds across constellations, baseline lengths, and modern
  multi-frequency data is untested.
- The fortified/unfortified split was measured on glibc + gcc 7.5 on x86-64.
  The shipped Windows binaries were then run directly and corrupt the
  coordinate silently — see "The same dial on the binaries people actually
  run". Emlid Reach's **source** is now confirmed to carry the defect and the
  unvalidated adoption, with a layout that takes the same payload lengths (see
  "A shipping receiver runs this code"), but **no receiver firmware binary has
  been examined**. The earlier expectation that Linux targets land in the
  *fortified* column is now **refuted for distro builds** — Debian's own
  armhf package imports no `*_chk` at all (see "The distro package is
  unfortified too") — which removes the basis for predicting that Reach
  aborts. Reach's own firmware is still unmeasured either way. Until a binary
  is checked, say "the source is affected", not "the product behaves this way".
- `dgps` being zeroed is guarded at `rtcm2.c:71` (`if (rtcm->dgps)`), so it
  silently disables DGPS correction output rather than faulting.
