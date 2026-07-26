# `decode_type1033` — station position corruption

Reproduction harness for a station-position attack against RTKLIB's RTCM3
type 1033 decoder.

**Measured against:** `tomojitakasu/RTKLIB`, branch `rtklib_2.4.3`, commit
`180043e` (2.4.3 b34, 2020-12-29). The same code is present unchanged on
`master` (2.4.2 p13, 2018-01-30).

---

## Summary

A single well-formed RTCM3 type 1033 message — correct length field, correct
CRC24Q, valid station ID — corrupts a rover's base-station coordinates by an
**attacker-tunable amount**. Choosing the length byte selects the magnitude,
from imperceptible, through a silent few-metre error, up to total loss of
solution.

**Which of two things happens depends on how the binary was compiled**, and
this turns out to be the most important fact here:

| build | outcome |
|---|---|
| glibc `_FORTIFY_SOURCE` active (`-O1`+ on most distros, the default for distro packages) | the fortified `strncpy` detects the overflow and **aborts the process** — one packet is a remote DoS |
| unfortified (`-O0`, or a toolchain without `_FORTIFY_SOURCE` — the norm for embedded/firmware builds) | the write goes through **silently** — tunable position corruption |

In the unfortified case the interesting band is a small one. A shift of
~0.4-2.5 m leaves RTKLIB reporting **Q=1 (RTK fixed)** — its highest quality
flag — while the position it emits is wrong by roughly the amount injected.
Nothing crashes, nothing is logged, and AddressSanitizer reports nothing.

That is the answer to the question the project started from: *can an attacker
manipulate a precision GNSS rover while it continues to report a healthy fix?*
Yes, and via a software path rather than RF — on the builds least likely to be
hardened, which is precisely the RTKLIB-derived firmware class.

## The mechanism

`decode_type1033` reads five descriptor strings, each an 8-bit length followed
by that many characters. It stages them in 32-byte locals with correctly
bounded read loops, then copies them into `rtcm->sta` with the *unbounded*
declared length ([src/rtcm3.c:905-910](https://github.com/tomojitakasu/RTKLIB/blob/rtklib_2.4.3/src/rtcm3.c#L905)):

```c
strncpy(rtcm->sta.rectype,rec,n1); rtcm->sta.rectype[n1]='\0';
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

Requires `refpos=POSOPT_RTCM` — base position taken from the correction
stream — which is the normal RTK configuration.

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

### The length byte is a magnitude dial

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

The exact magnitude for a given `n1` depends on the base station's actual
coordinates, since it is the float mantissa being truncated. An attacker who
does not know them can sweep `n1` upward from 209 until the effect is the size
they want.

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
equivalence is measured on these two builds; it is not a general claim about
every target, and ARM in particular is untested.

Both distributions also ship the real-time applications `rtknavi.exe` and
`strsvr.exe`, and those binaries contain the same decoder — the trace strings
`rtcm3 1033 length error: len=%d` and `rtcm3 1033: ant=%s:%s rec=%s:%s:%s` are
present in each. They are GUI programs and were not driven here. So what is
measured on Windows is the decode and the coordinate corruption; the
subsequent adoption into the baseline by `update_antpos()` is measured on the
Linux build only.

Demo5 shipped 2.5.1 on 2026-06-22, **13 days after** the FuzzingLabs issues
were filed, with the bug unchanged.

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

What remains for a single packet-to-propeller chain is to drive the rover
position from the simulated aircraft in real time instead of a fixed
coordinate, and close the loop back through the NMEA bridge.

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

```sh
git clone -b rtklib_2.4.3 https://github.com/tomojitakasu/RTKLIB
RTKLIB=./RTKLIB ./run.sh
RTKLIB=./RTKLIB ASAN=1 ./run.sh
```

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
(`rtcm3.c:469`) and `decode_type1008` (`:507`), which is not examined here.

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
  fields, cannot reach it either — 1033 is the only one of the three that can.
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

- **The vehicle result is a simulation, and the offset is injected, not
  decoded.** ArduPilot SITL is fed the measured offset through its GPS glitch
  parameters; it is not running RTKLIB and never sees the malicious RTCM3.
  What that demonstrates is the consequence of a position offset of this size
  on a real autopilot's control loop — the open question the RTKLIB work could
  not answer. No real aircraft was involved.
- **Precisely what is and is not one continuous chain.** Malicious message →
  RTKLIB → corrupted position → NMEA → an autopilot holding a fix on it *is*
  measured end to end, over both file and serial transports. The vehicle's
  physical response is measured separately. Joining them needs RTKLIB to
  receive rover observations from wherever the aircraft actually is, which
  means either synthesising those observables or using a real receiver under
  a real sky. Neither is done.
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
- Offsets are x86-64 / gcc. The shipped 32-bit Windows build turns out to give
  identical thresholds and magnitudes (see "The same dial on the binaries
  people actually run"), because everything in `sta_t` ahead of `pos` is
  `char` arrays and `int`s. ARM remains untested, and the thresholds must
  still be recomputed for any target whose alignment differs.
- The magnitude for a given `n1` is dataset-specific — it depends on the base
  station's coordinate values, since mantissa bytes are being truncated.
- Only one rover/base pair (2005, GPS-only) was tested. Whether the Q=1
  behaviour holds across constellations, baseline lengths, and modern
  multi-frequency data is untested.
- The fortified/unfortified split was measured on glibc + gcc 7.5 on x86-64.
  The shipped Windows binaries were then run directly and corrupt the
  coordinate silently — see "The same dial on the binaries people actually
  run" — but **no embedded receiver firmware has been examined**. Emlid
  Reach, ArduSimple and similar are Linux-based and would plausibly land in
  the *fortified* column — the opposite of the desktop applications. That is
  unverified and worth doing before claiming anything about hardware products.
- `dgps` being zeroed is guarded at `rtcm2.c:71` (`if (rtcm->dgps)`), so it
  silently disables DGPS correction output rather than faulting.
