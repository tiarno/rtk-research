# Handoff Notes

**Session date:** 2026-07-26 (previous session 2026-07-25)

## Since the last handoff

Two things closed out. Both are written up in
[research/README.md](../research/README.md); this is the summary.

**The closed loop works and the numbers are trustworthy.** The blocker below
turned out not to be latency — that measured 130 ms, faster than a real GPS.
The real cause was RTKLIB's NMEA reporting 0.00 knots regardless of motion,
which ArduPilot's EKF3 fuses by default; `EK3_SRC1_VELXY 0` fixes it.
`prcopt.dynamics` does *not*, measured against a known 1 m/s ramp.

|  | control, 0 injected | attacked, 691 injected |
|---|---|---|
| GPS vs. truth after | 0.00 m | 2.08 m |
| displacement holding | — | 2.16 m |
| waypoint miss | 0.09 m | 1.81 m |

Agrees with the open-loop figures (1.90 m, 1.87 m) measured a different way.
**Always run `./loop_demo.sh 0` first** — two harness defects produced
attack-shaped displacements of 26 m and 113 m with no attack present.

**The shipped Windows binaries are measured, not asserted.** `convbin.exe` from
both the official distribution and demo5 2.5.1 corrupt the station coordinate
silently, rc=0, with the magnitude dial reproducing to the last digit and 32-bit
and 64-bit identical. `_FORTIFY_SOURCE` is glibc-only; these are Embarcadero
builds where the abort has no equivalent to enable.

Open items now: the displacement *direction* does not line up between the
closed and open loop runs (magnitudes do — quote those, not the sign); the
`EK3_SRC1_VELXY` workaround is a deviation from stock config forced by the
harness; no embedded receiver firmware examined; ARM untested.

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

**Nothing is committed.** Working tree has modifications to `gnss_sim.c`,
`mav_pos.py`, `ardupilot_demo.py`; `inject_relay.py` and `loop_demo.sh` are
untracked; the two junk binaries are staged for deletion.

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

**Do not quote the 39 m drift or the 157 m waypoint miss from this run.** They
are the instability, not attack effects, and nothing from the closed loop
should go into `research/README.md` until the vehicle is stable.

## Next Steps

1. Measure the end-to-end loop latency, then set `GPS_DELAY_MS` / the EK3 GPS
   delay to match, or shorten the pipeline (the FIFO and per-stage settles are
   the obvious candidates).
2. Re-run and confirm the aircraft holds position with the bias present, which
   is the stable behaviour the open-loop demo already measured (~1.9 m).
3. Only then measure the waypoint miss, and add the closed-loop result to
   `research/README.md` — replacing the "what still prevents a single
   packet-to-propeller chain" caveat.
4. Commit. Nothing from this session is committed yet.

## Key Parameters/Settings

| | |
|---|---|
| branch | `master` |
| RTKLIB | `~/RTKLIB` in WSL, branch `rtklib_2.4.3`, commit `180043e` |
| ArduPilot SITL | `~/apsitl/arducopter` (prebuilt ArduCopter 4.7.0) |
| run command | `RTKLIB=/home/tim/RTKLIB BIN=/home/tim/apsitl/arducopter bash ./loop_demo.sh 212` from `/mnt/c/Users/tim/work/rtk/research` in WSL Ubuntu |
| `LEN` | 212 — declared `rectype` length, selects a 2.4 m base error |
| `DELAY` | 50 s of clean flight before injection starts |
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
