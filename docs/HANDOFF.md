# Handoff Notes

**Session date:** 2026-07-26 (second session that day)

## Since the last handoff

**The displacement sign is resolved, and it cost a number.** The two runs
never disagreed about physics. The closed-loop harness armed its injection on
a timer counted from RTKLIB's connect, which put it behind every startup delay
in the chain, and it lost the race: the GPS started lying at t=44.2 s while the
aircraft did not leave the ground until t=47.4 s. Phase 1 was never clean, and
the GUIDED hold target — read from the vehicle's own reported position once
airborne — was captured from a position the GPS was already falsifying. The
2.16 m "displacement while holding" was a takeoff transient anchored to that
lie. **It is withdrawn.**

Fixed by inverting the control: `ardupilot_demo.py --trigger-file` creates a
file once airborne and holding, and `inject_relay.py --trigger` waits for it.
No clock is involved, and the sequencing cannot race. Re-measured:

|  | control, 0 injected | attacked, 520 injected |
|---|---|---|
| GPS vs. truth after | 0.00 m | 1.91 m |
| displacement holding | — | 1.89 m, **opposite** the offset |
| waypoint miss | 0.09 m | 1.81 m |

Now agrees with the open-loop run component by component to within 7 cm — N,E
of the injected offset, the displacement and the miss — not just in magnitude.
So **"it repositioned to correct a drift that never happened" is now supported
by both runs**, which is the line the last handoff wanted and could not have.

`parse_sitl_log.py` gained two guards so this cannot recur silently: attack
onset now requires a *sustained* offset (a clean control run's 30 m transit
spikes 3 m of GPS lag and was being read as an attack), and it refuses to
report a displacement at all if the attack predates takeoff, naming the reason.
`sign_check.py` is new — truth, GPS and EKF in one frame, which is what made
the diagnosis obvious.

**Always run `./loop_demo.sh 0` first** — three harness defects have now
produced attack-shaped displacements with no attack present.

**Earlier that day:** the closed loop's instability was RTKLIB's NMEA reporting
0.00 knots regardless of motion, which ArduPilot's EKF3 fuses by default;
`EK3_SRC1_VELXY 0` fixes it and `prcopt.dynamics` does not, measured against a
known 1 m/s ramp. Loop latency measured 130 ms and was exonerated. The shipped
Windows binaries (`convbin.exe`, official and demo5 2.5.1) corrupt the station
coordinate silently, rc=0, magnitude dial reproducing to the last digit, 32-
and 64-bit identical; `_FORTIFY_SOURCE` is glibc-only and these are Embarcadero
builds where the abort has no equivalent to enable.

**The shipped Windows binaries are measured, not asserted.** `convbin.exe` from
both the official distribution and demo5 2.5.1 corrupt the station coordinate
silently, rc=0, with the magnitude dial reproducing to the last digit and 32-bit
and 64-bit identical. `_FORTIFY_SOURCE` is glibc-only; these are Embarcadero
builds where the abort has no equivalent to enable.

## Where this is going

The work is destined for a conference talk **with a live demo**, decided
2026-07-26. No deadline. That changes the priorities below: a live demo has to
survive someone asking "why is that setting changed?", so harness deviations
from a stock configuration are load-bearing rather than footnotes, and startup
reliability matters as much as the numbers.

## Next steps, in the order I would take them

Effort figures are rough and assume the environment is already set up (see Key
Parameters).

**1. Emit our own NMEA RMC — ~half a day. The one that matters for the demo.**
RTKLIB's rtksvr path populates no solution velocity (measured: zero with
`prcopt.dynamics` on and off, against a rover fed a known 1 m/s ramp), so its
RMC always reports 0.00 knots and the demo needs `EK3_SRC1_VELXY 0` to stay
stable. Rather than chase RTKLIB's filter, stop using its NMEA writer and
format RMC in `e2e_harness.c`, deriving speed and course by differencing
successive solutions at 5 Hz. Then the demo runs on stock parameters. Say
plainly that differencing stands in for the Doppler velocity a real receiver
reports.

**2. ARM offsets — ~1 hour, near-certain outcome.** Cross-compile the offset
probe for aarch64 and run it under qemu-user. The 32-vs-64-bit result already
showed why it should be identical: everything ahead of `pos` in `sta_t` is
`char` arrays and `int`s. Cheaply converts a stated unknown into "one payload
length works on every target checked".

**3. `decode_type1007` / `1008` — ~1 hour.** Same harness, different message
type. Expect a negative result worth stating precisely: those fields stop short
of `pos`, so memory-safety only, no positioning impact. It answers "why 1033?"

**4. A patch PR to RTKLIB — nearly free.** The fix is a three-line clamp. It
will probably sit unmerged, which is the point: "here is the four-line fix,
filed, still unmerged" closes better than "still unpatched".

**5. Real hardware — a few hundred dollars, a weekend, biggest credibility
gain.** Note the F9P cannot be the target: it does not run RTKLIB. The setup is
an F9P feeding real observations to **RTKNAVI on Windows** — now measured as
unfortified — with the 1033 injected into an NTRIP correction stream. Upgrades
the result from simulated to real satellites, real receiver, shipped software.

**6. Embedded firmware (Emlid Reach) — uncertain, 90 min to find out.** Check
first whether a ReachView image is downloadable without owning the device. If
it is, binwalk plus `objdump` for `*_chk` imports. Either answer is a good
slide, since the prediction is that Linux-based hardware lands in the *abort*
column, opposite the desktop apps.

**Deliberately not doing: RF delivery.** Technically easy with the Heltec gear,
but 433/915 MHz is where real survey and agricultural rigs operate. "No RF was
transmitted into open air" is a genuine virtue of this work. If it is ever
wanted, do it conducted — attenuator or shielded enclosure — never radiated.

## Standing caveats

- `EK3_SRC1_VELXY 0` is a harness workaround, not an attack property (item 1).
- No embedded receiver firmware examined (item 6); ARM untested (item 2).
- Windows measurement covers the decode and coordinate corruption, not the
  real-time adoption via `update_antpos()` — the GUI apps were not driven.

---

Everything below is from the 2026-07-25 session and is retained for the
reasoning, not as current state.

The authoritative record of the research itself is
[research/README.md](../research/README.md). This file is only the working
state: what moved this session, what is broken, and what to do next.

## What Was Done

Closed the last gap in the writeup's Limitations section — a single
packet-to-propeller chain, with the offset reaching the aircraft *only* as a
malicious RTCM3 1033 in the correction stream. It now runs end to end.

- **Restored the RTKLIB checkout.** It was missing from WSL, so nothing built.
  Cloned at the pinned commit `180043e` (2.4.3 b34) to `~/RTKLIB`.
- **Broke the startup deadlock in `gnss_sim` live mode.** It emitted one epoch
  per stdin line, so no observables existed until the vehicle fed a position —
  but the vehicle needed a fix to exist. Live mode now free-runs at `rate` Hz
  off its own clock, with a reader thread updating the rover position, starting
  from the base coordinate. Verified standalone: 150 epochs served and 106
  solutions with zero positions fed.
- **Fixed a vertical feedback runaway.** `mav_pos.py` fed `GLOBAL_POSITION_INT`
  altitude — the vehicle's own *estimate* — back in as truth, so the estimate
  defined the observables that then confirmed it. Solution height ran 75.8 m to
  −143 m in 40 s and the aircraft never got airborne. Truth altitude now comes
  from `SIM_STATE`; if it never arrives the height is held constant rather than
  falling back to the estimate.
- **Split the MAVLink endpoints.** The position feed and the flight driver both
  connected to SERIAL0, which takes one client at a time, so the second got EOF
  — indistinguishable from a vehicle that will not arm. Feed is on SERIAL1.
- **Stopped the flight driver double-counting the attack.** `ardupilot_demo.py`
  applied its own `SIM_GPS1_GLTCH_*` offset; added `--no-glitch` for the loop.
  Its waypoint was also hardcoded to the RINEX site, 3.4 km from where the loop
  flies — now anchored to the actual hold position and passed to the parser.
- **Fixed `inject_relay.py` stats** reporting `0 frames, 0 injected` while
  working (counts were kept on a second, unused splicer).
- **Removed two junk binaries** (`research/:5901`, `research/:5902`) committed
  by accident in `c49bfe2`, and made batch mode reject a port as an output path.

## Current State

The chain runs: SITL truth -> `gnss_sim` -> on-path relay -> RTKLIB -> NMEA ->
SITL's GPS. The attack propagates at **Q=1 (RTK fixed)**:

```
clean    35.132066148  139.624302129  75.7912   base -3978242.4348
attack   35.132075630  139.624284796  74.3630   base -3978240.0000
         N +1.05  E -1.58  U -1.43  ->  2.4 m,  Q=1 in both
```

691 injections, base position adopted from the stream, no file editing
anywhere. The aircraft armed, flew all three phases and landed.

*(All of this is committed now — `ea6f5f2` onward, merged to `master`.)*

## What's Blocked

**The vehicle destabilises, and the cause is the harness, not the attack.**
The GPS-vs-truth offset stays pinned at ~2 m for the whole flight — the attack
does exactly what the writeup documents. The aircraft's *true* position is what
diverges:

```
t=45..57   within +-0.5 m, offset 1.90 m     <- stable, attack already present
t=59  +-1 m    t=71  +-3 m    t=83  +-7 m
t=87  -26 m    t=91  -68 m    t=95  -103 m   t=101  -113 m
```

Growing oscillation, period ~9 s, amplitude roughly doubling per cycle. That is
a delayed-feedback instability: the loop latency (mav_pos -> FIFO -> epoch ->
RTCM -> relay -> RTKLIB solve -> NMEA -> SITL) is far longer than the ~200 ms
GPS delay ArduPilot's EKF assumes.

> **That last sentence was wrong — REFUTED 2026-07-26.** The loop delay
> measures 130 ms, faster than a real GPS. The actual cause was RTKLIB's NMEA
> reporting zero velocity to an EKF that fuses it. The observation of the
> oscillation was sound; the explanation was not.

**Do not quote the 39 m drift or the 157 m waypoint miss from this run.** They
are the instability, not attack effects, and nothing from the closed loop
should go into `research/README.md` until the vehicle is stable.

*(Superseded — all four are done. The current plan is "Next steps, in the order
I would take them" near the top. Item 1 there is what came out of item 1 here
going the way it did.)*

## Key Parameters/Settings

| | |
|---|---|
| branch | `master` |
| RTKLIB | `~/RTKLIB` in WSL, branch `rtklib_2.4.3`, commit `180043e` |
| ArduPilot SITL | `~/apsitl/arducopter` (prebuilt ArduCopter 4.7.0) |
| run command | `RTKLIB=/home/tim/RTKLIB BIN=/home/tim/apsitl/arducopter bash ./loop_demo.sh 212` from `/mnt/c/Users/tim/work/rtk/research` in WSL Ubuntu |
| control run | the same with `0` instead of `212` — injection disabled. Run it *first*; it should land within centimetres |
| latency probe | `RTKLIB=/home/tim/RTKLIB bash ./loop_latency.sh 90` — no vehicle, prints the loop delay |
| `LEN` | 212 — declared `rectype` length, selects a 2.4 m base error |
| attack trigger | `$T/attack.go`, created by the flight driver at phase 2. Replaced the `DELAY` timer, which raced the takeoff |
| `RUN` | 260 s — must outlast the whole flight profile or SITL loses its GPS mid-flight |
| ports | 5901 base, 5902 rover, 5911 relay, 5903 NMEA, 5760 SITL SERIAL0, 5762 SERIAL1 |
| base ECEF | `-3978242.4348,3382841.1715,3649902.7667` |
| scratch | `/tmp/rtk-loop` (logs: `sim.log`, `relay.log`, `rtklib.log`, `mavpos.log`, `sitl.log`, `flight.log`) |

Two environment traps worth remembering:

- `pkill -f <pattern>` matches the invoking `bash -lc '...'` command line
  itself if the pattern appears in it, so an ad-hoc cleanup command can kill its
  own shell and exit silently.
- `$VAR` does not survive `wsl.exe -- bash -lc '...'` from Git Bash. Use
  explicit paths or a script file, and `MSYS_NO_PATHCONV=1` for `/mnt/...`
  arguments.

## Files Changed

| file | change |
|---|---|
| `research/gnss_sim.c` | self-paced live loop + position reader thread; batch mode rejects a port as an output path |
| `research/mav_pos.py` | truth altitude from `SIM_STATE` (requested by message id); no estimate fallback |
| `research/ardupilot_demo.py` | `--no-glitch`; waypoint anchored to the hold position and printed for the parser |
| `research/loop_demo.sh` | untracked — split MAVLink endpoints, `RUN` 170 to 260, passes `--target` to the parser |
| `research/inject_relay.py` | untracked — on-path relay; stats now kept on the splicer doing the work |
| `research/:5901`, `research/:5902` | deleted (staged) |

## Network Interpretation — RETRACTED

Kept because the conclusion was published in an earlier version of this file.

An earlier version claimed that `rtklibexplorer/RTKLIB` is the dominant hub of
the fork network, with upstream "clearly secondary." **That conclusion is
withdrawn — it was an artifact of an incomplete crawl, not a property of the
ecosystem.**

Two defects produced it:

1. **Truncated crawl.** `get_forks()` in `rtklib_fork_network.py` assigns
   `CACHE[repo_id] = batch` inside the pagination loop, so each page overwrites
   the previous one, and a cache *hit* short-circuits the crawl entirely. The
   resulting graph covers ~6% of upstream's ~1,800 forks (and the oldest ones,
   since the API call sorts by `oldest`) against ~100% of rtklibexplorer's 367.
   The hub was manufactured by the sampling.
2. **Centrality is meaningless on this graph.** GitHub fork graphs are trees —
   every fork has exactly one parent. Betweenness centrality on a tree is a
   monotone function of subtree size, so it cannot surface a chokepoint that
   simple descendant-counting would miss.

Separately, fork count measures curiosity, not deployment: a fork is one click,
and most are never touched again.

The fork-mapping line of work has been **dropped**. `rtklib_fork_network.py`,
`rtklib_fork_cache.json`, `rtklib_fork_graph.graphml`, and
`rtklib_seed_nodes.csv` are retained only as a record of the attempt. Do not
cite any figure from them.
