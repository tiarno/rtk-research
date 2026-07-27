# Handoff Notes

**Session date:** 2026-07-27

## 2026-07-27: two claims tightened ahead of disclosure

Both were things already in writing that would not have survived contact with
the people best equipped to check them. Neither changes a result.

**"Nothing is logged" was imprecise, and the precise version is better.**
`decode_type1033` does trace, at level 3 — but it prints the *staging buffers*,
which the read loops cap at 31 characters. A message declaring `n1=255` logs a
line indistinguishable from a benign one, the attacker chooses those 31
characters, and the declared length never appears at any level. `update_antpos()`
— the function that adopts the corrupted coordinate — has no trace call at all;
the only trace of it is `svr->nmsg[index][4]++`. Written up as "What an operator
could see, with tracing fully enabled" in `research/README.md`, and corrected in
`README.md` and `eli5.md`. **The instrument exists and is pointed at the wrong
thing** is now the line, and it doubles as the one defence a vendor could ship
in an afternoon (§11).

**`refpos=POSOPT_RTCM` is not the default, and the honest framing is stronger
than the one it replaces.** `options.c:503` initialises `antpostype_` to 0
(LLH). But of the seven example configs in the tree, `rtkrcv/conf/rtk.conf` is
the only one configured for real-time RTK against an RTCM3 stream, and it is
the only one setting `ant2-postype=rtcm`. The rest are single-point or
post-processing, which have no correction stream to take a base position from.
So it is not "the normal RTK configuration" (vague, and challengeable) but
"every shipped config that does RTK at all" (checkable, and stronger). Table in
`research/README.md` under "Which configurations are exposed"; §11's operator
advice and the audience-question table updated.

## Disclosure timeline

Talk §11 turns on this, so it is recorded here as it happens rather than
reconstructed later.

| date | what | state |
|---|---|---|
| 2026-06-09 | FuzzingLabs (@raefko) file upstream issues #796–799; #799 is the type 1033 bug | all four still **open**, one comment each, no maintainer reply |
| 2020-12-29 | last commit to upstream's `rtklib_2.4.3` release branch | — |
| 2026-07-19 | this repo made public | — |
| 2026-07-27 | **repo made private** — a pause to think, not a retraction | reversible; see below |
| 2026-07-27 | **comment posted on #799**: the overflow reaches `sta.pos`, `antdes` cannot, the real-time path adopts it unguarded while `postpos.c:843` guards, Q=1 maintained, every measured build unfortified | awaiting response |
| 2026-07-27 | **Emlid notified by email** — their `reach` fork carries the defect and the inlined unguarded adoption; asked whether `_FORTIFY_SOURCE` is active in shipped firmware | awaiting response |

The #799 comment is deliberately self-sufficient: every claim in it is
checkable against RTKLIB's own source, so it stands as a dated priority marker
whether or not this repo is public. Held back from it: the four-rung magnitude
behaviour and the `n1=211` universal bound, the clamp (belongs in the PR), the
misalignment defect (belongs in its own issue), and Emlid entirely.

**Repo visibility.** Public 2026-07-19 to 2026-07-27, now private. Two things
follow. Priority no longer rests on the repo — it rests on the #799 comment,
which is why that was written to stand alone. And while it is private there is
a clean window to rewrite `1d5645f`, whose commit body contains "is the thing
FuzzingLabs cannot match" — public for eight days, almost certainly never
cloned, so a rebase would genuinely remove it rather than leaving it reachable
by SHA. Cost is the hash references in the commit table below, which have been
repaired once already (`b1f69a2`).

**The patch is written and verified but deliberately not filed.** `check_clamp.sh`
measures it: benign streams byte-identical, all three attack variants left at
truth, UBSan finding gone with the control firing first. Holding the PR until
there is a response to the #799 comment — filing it immediately would spend the
one piece of leverage the comment has, and §11's slide reads better as "here is
the fix, filed, still unmerged" than as a PR nobody was asked for.

**Still to do:** the PR when the time comes, and a decision on whether the
misalignment defect gets filed as its own issue. A FuzzingLabs email is now
optional — commenting on #799 notifies @raefko automatically, since it is
their issue.

---

**Previous session:** 2026-07-26 (second session that day)

## Current state, in one paragraph

The closed loop works on a **stock ArduPilot parameter set** and now runs at
**`n1=211`** — the rung whose 2 m quantum bounds the error against *any* base
station, rather than `n1=212`, whose 512 m quantum happened to land on 2.4 m
against the old base. Control 0.03 m, attacked 1.39 m waypoint miss, 1.36 m
displacement opposite the offset. Two claims that were load-bearing earlier are
now **refuted by measurement and corrected in every document**: that
fortification is the distro default (Debian's own `rtklib`, on ARM, imports no
`*_chk` at all) and that the length byte is a fine-grained dial (four rungs,
each 256× the last). The defect is confirmed present in Emlid's `reach` fork,
so this is a product bug and not only a library bug. The vertical third of the
error is measured and is a **negative** — the baro outvotes it — which bounds
the attack and names the defence. The talk now has an outline
([talk-outline.md](talk-outline.md)), and the provenance claims are re-runnable
rather than asserted (`check_fork.sh`, `check_binary.sh`, `check_image.sh`).
Nothing is blocked.

**The research is no longer the bottleneck; the demo staging is.** Everything
claimed is measured, every document agrees, and the demo runs on a length that
generalises. What is missing is the visual build — map, two icons, a persistent
FIXED indicator — and a rehearsal.

The one thing to carry forward: **run `./loop_demo.sh 0` before quoting any
closed-loop number.** Three harness defects have produced attack-shaped results
with no attack present, and the control run is what caught each of them. A
fourth — RTKLIB's frozen RMC course — degraded the attacked run instead, and
was caught only because the displacement disagreed with a figure measured a
different way. Both checks earn their keep.

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

> Those figures still carry `EK3_SRC1_VELXY 0`. They were superseded later the
> same session by a stock-parameter re-run — see the next section, and quote
> that table, not this one. The conclusion is unchanged; the numbers moved by
> a few centimetres.

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
`EK3_SRC1_VELXY 0` worked around it and `prcopt.dynamics` did not, measured
against a known 1 m/s ramp. Loop latency measured 130 ms and was exonerated.
The shipped Windows binaries (`convbin.exe`, official and demo5 2.5.1) corrupt
the station coordinate silently, rc=0, magnitude dial reproducing to the last
digit, 32- and 64-bit identical; `_FORTIFY_SOURCE` is glibc-only and these are
Embarcadero builds where the abort has no equivalent to enable.

## The demo now runs on stock ArduPilot parameters

`EK3_SRC1_VELXY 0` is **gone**, and with it the last tuning deviation an
audience could ask about. The only parameters `loop_demo.sh` sets now are the
ones that wire the harness up: frame class, GPS type, serial protocol, stream
rates.

`NMEA_VEL=1` makes `e2e_harness.c` format the NMEA itself, filling
`sol.rr[3..5]` by differencing successive solutions at 5 Hz. GGA/GSA/GSV are
still RTKLIB's own writers and byte-identical; only RMC is ours, because of the
second defect below.

|  | control, 0 injected | attacked, 520 injected |
|---|---|---|
| GPS vs. truth after | 0.00 m | 1.92 m |
| displacement holding | — | 1.86 m, **opposite** the offset (residual 0.04 m) |
| waypoint miss | **0.04 m** | 1.86 m |

The control lands within **4 cm**, better than the 9 cm the workaround
achieved, and the attacked run still agrees with the open-loop measurement to
within 5 cm per component. Removing the deviation made the result *better*,
which is the strongest possible answer to "why is that setting changed?" — it
was compensating for RTKLIB's NMEA writer, never for the attack.

**Two defects had to be fixed to get there, and the second is the interesting
one.**

*Differencing alone was not enough.* `outnmea_rmc()` reports the previous
course whenever speed is below 1 m/s (`static double dirp` in `solution.c`,
starting at 0.0), so a correct speed arrives with a frozen bearing. Measured
with no vehicle in the loop: fed 0.5 m/s due east, RTKLIB's RMC says 0.499 m/s
on a course of 0.0° — 90° wrong. ArduPilot rebuilds velocity as speed × course
and a hovering multirotor lives entirely in that band, so it is a *consistent*
error the estimator integrates rather than noise it averages away. The aircraft
oscillated ±3 m while holding, while the waypoint leg — flown above 1 m/s where
the course is live — looked perfect. `own_rmc()` computes the course at every
speed. Verified: 90.0° at 0.5 m/s east, 225.1° at 0.3 m/s south-west.

*A stale binary.* The first `own_rmc()` attempt failed to compile (`NMEA_TID`
and `KNOT2M` live in `solution.c`, not `rtklib.h`) and both scripts silently
ran the *previous* binary, because the build check tested `[ -x $T/e2e_loop ]`
— which passes when the old file is still there. It cost a full flight and
nearly the wrong conclusion. Both scripts now `rm -f` first and test gcc's exit
status.

## Startup reliability — three guards added

A live demo has to fail loudly and be immediately retryable. None of these
were true this morning.

- **`require_port` after every stage.** A leftover process held :5901, so
  `gnss_sim` never bound, the chain ran empty, and it surfaced four minutes
  later as `EKF never became ready` (flags 0x0400). On stage that looks exactly
  like the attack failing. Now it aborts in 10 s naming the port and the log.
- **`-DSVR_REUSEADDR`.** RTKLIB only sets `SO_REUSEADDR` on a TCP server under
  this flag, so every run left :5901/:5902/:5903 unbindable for the TIME_WAIT
  window and the *next* run died at startup. A demo you cannot immediately
  retry is not a demo.
- **Build failures are fatal**, as above.

Two environment traps re-confirmed the hard way: `pkill -f loop_demo.sh` kills
the invoking `bash -lc` too (it matches its own command line), and a
`tail`-piped run shows no output at all until it exits — watch
`/tmp/rtk-loop/flight.log` directly instead.

## Where this is going

The work is destined for a conference talk **with a live demo**, decided
2026-07-26. No deadline. That changes the priorities below: a live demo has to
survive someone asking "why is that setting changed?", so harness deviations
from a stock configuration are load-bearing rather than footnotes, and startup
reliability matters as much as the numbers.

## Next steps, in the order I would take them

Effort figures are rough and assume the environment is already set up (see Key
Parameters).

> **These are the *research* items.** Talk-preparation tasks — demo visuals,
> the recorded fallback, rehearsing a failed start, hardware to order — live in
> [talk-outline.md](talk-outline.md#pre-submission-checklist) so the two lists
> cannot drift apart. If you are picking up work and the goal is the talk, read
> that checklist first: on current state it is the binding constraint, not
> anything below.

**1. ARM offsets — mostly overtaken, ~30 min if wanted.** Debian's shipped
armhf binaries are now in hand (`/tmp/deb`), so ARM builds no longer need qemu
to exist — but the `sta_t` offsets on ARM are still unconfirmed, and that is
what a payload length for an ARM target depends on. Cheapest remaining version:
compile the offset probe with `arm-linux-gnueabihf-gcc` and print
`offsetof(sta_t,pos)`; no emulation needed since nothing has to run.

**2. `decode_type1007` / `1008` — ~1 hour.** Same harness, different message
type. Expect a negative result worth stating precisely: those fields stop short
of `pos`, so memory-safety only, no positioning impact. It answers "why 1033?"

**3. A patch PR to RTKLIB — nearly free.** The fix is a three-line clamp. It
will probably sit unmerged, which is the point: "here is the four-line fix,
filed, still unmerged" closes better than "still unpatched".

**4. Real hardware — a few hundred dollars, a weekend, biggest credibility
gain.** Note the F9P cannot be the target: it does not run RTKLIB. The setup is
an F9P feeding real observations to **RTKNAVI on Windows** — now measured as
unfortified — with the 1033 injected into an NTRIP correction stream. Upgrades
the result from simulated to real satellites, real receiver, shipped software.

**5. Embedded firmware (Emlid Reach) — SOURCE DONE 2026-07-26, binary blocked.**
`emlid/RTKLIB` branch `reach` carries the defect unchanged, the same `sta_t`
layout (so the same payload lengths work), and the unvalidated adoption inlined
into `updatesvr()` at `rtksvr.c:219`. Written up in `research/README.md`. That
converts "a bug in a hobby library" into "a bug in a product you can buy", and
ArduPilot documents Reach feeding a flight controller over ERB with corrections
arriving on the telemetry radio — the harness chain with a real product in it.

*The Navio image was pulled and is a dead end for RTKLIB, but paid off anyway.*
`emlid-raspbian-20220608.img` (718 MB, sha256 `d16b66d5…`) ships **no RTKLIB**:
in the whole 3.7 GB rootfs the only `str2str` hits are OpenLDAP symbols matching
as a substring, and the only `RTKLIB` hit is an APT metadata stanza. Read
rootless with `debugfs` on a `dd`-carved partition — no `sudo`, which the
project settings deny.

That APT stanza is what paid off: **Debian packages RTKLIB 2.4.3.b34**, the
exact version measured here, for 12 architectures. The armhf console apps were
fetched and checked, and they **refute the prediction that Linux targets abort**
— no `*_chk` imports at all, plain `strncpy`/`sprintf` present, decoder
statically inside `rtkrcv`. Written up as "The distro package is unfortified
too" in `research/README.md`. Every build actually measured now — two Windows
distributions and one Linux/ARM distro package — is in the silent column.

*Still open: the Reach firmware binary itself.* `files.emlid.com` 403s all
image paths and the Flash Tool fetches at runtime. Two ways left: observe what
URL the Flash Tool requests (free, uncertain), or buy a Reach M2 (~$300,
certain). Note the prediction that it would abort no longer has a basis.

**RF delivery: now planned, and conducted only.** Superseded 2026-07-26 — the
talk wants it. The constraint that produced the original "not doing" stands
unchanged and is the design, not a caveat: 433/868/915 MHz is where real survey
and agricultural rigs operate, so **everything goes down coax through
attenuators into a shielded enclosure, never a radiated signal**. "No RF was
transmitted into open air" remains a virtue of this work and is also the only
version that is reliable on a conference floor.

The Emlid finding changed the priority. Reach uses **LoRa** for its base↔rover
correction link (902–928 MHz US, 863–870 MHz EU), which is SX1262 — the same
chip as the Heltec V3 boards already on hand. Professional rigs (Trimble
TDL450, Satel 4Pro) are a different animal: GMSK/4FSK, 403–473 MHz, transparent
serial. Full plan, both paths, and the hardware list in
[talk-outline.md](talk-outline.md#8-delivering-it-over-the-air).

## Commits, most recent session first

**2026-07-26, later session.** Eight commits, `3cd70d4..b55a92f`:

| commit | what |
|---|---|
| `3cd70d4` | measured the rungs 209–214 — the dial has four, `n1=211` is the one that generalises; resynced the ELI5, which still carried withdrawn numbers and a workaround that no longer existed |
| `4f27f64` | Emlid `reach` fork confirmed to carry the defect, the layout and the unguarded adoption — a product bug, not only a library bug |
| `81c0c73` | **refuted** the prediction that Linux targets abort: Debian ships RTKLIB 2.4.3 b34 for 12 architectures and the armhf build is unfortified |
| `5f82c3e` | moved the demo to `n1=211` at a base sited to make it visible; control 0.03 m, attacked 1.39 m |
| `5ad69c4` | doc consistency pass — two claims this session falsified were corrected in every document, not just where they originated |
| `181f6e7` | measured the vertical: a 1.12 m height lie moved the aircraft 0.04 m, because the baro outvotes it. The axis with a redundant sensor resisted |
| `1d5645f` | the talk outline, the conducted-RF delivery plan, and the hardware list |
| `b55a92f` | surfaced the provenance tooling — `check_fork.sh`, `check_binary.sh`, `check_image.sh`, `pick_base.py` — so the Emlid/Debian/Navio claims are re-runnable rather than asserted |

**2026-07-26, earlier session.** *(These two were originally recorded here as
`e973bdd` and `5b9a0f5`, which are not in the repo — the branch was rebased
after the note was written. The real hashes are below; the file lists are
unchanged.)*

Committed in `fb8a3f7` (the sign resolution):

| file | change |
|---|---|
| `research/inject_relay.py` | `--trigger PATH`: wait for a file instead of counting seconds |
| `research/ardupilot_demo.py` | `--trigger-file PATH`: create it at phase 2, once airborne and holding |
| `research/loop_demo.sh` | uses the trigger; `DELAY` gone |
| `research/parse_sitl_log.py` | sustained-offset onset; refuses a displacement if the attack predates takeoff; phase 3 no longer keyed off the attack time |
| `research/sign_check.py` | new — truth, GPS and EKF position in one frame |
| `research/README.md`, `docs/HANDOFF.md` | corrected numbers, third harness defect written up |

Committed in `034d8a7` (the stock-parameter demo):

| file | change |
|---|---|
| `research/e2e_harness.c` | `derive_vel()` + `own_rmc()` + `NMEA_VEL=1` own-NMEA path; `DYNAMICS` comment corrected to say it does not work |
| `research/loop_demo.sh` | `NMEA_VEL=1` replaces `DYNAMICS=1`; `EK3_SRC1_VELXY 0` removed from `loop.parm`; `require_port` after each stage; fatal build failures; `-DSVR_REUSEADDR` |
| `research/loop_latency.py` | `feed --ramp/--ramp-dir`, new `speed` subcommand checking speed *and* course |
| `research/loop_latency.sh` | `MODE=speed`; same build fixes |
| `research/README.md`, `docs/HANDOFF.md` | stock-parameter numbers, the `dirp` course defect written up |

## Key Parameters/Settings

| | |
|---|---|
| branch | `master` |
| RTKLIB | `~/RTKLIB` in WSL, branch `rtklib_2.4.3`, commit `180043e` |
| ArduPilot SITL | `~/apsitl/arducopter` (prebuilt ArduCopter 4.7.0) |
| run command | `RTKLIB=/home/tim/RTKLIB BIN=/home/tim/apsitl/arducopter bash ./loop_demo.sh` from `/mnt/c/Users/tim/work/rtk/research` in WSL Ubuntu — `LEN` now defaults to 211 |
| control run | the same with `0` — injection disabled. Run it *first*; it should land within centimetres (last: 0.03 m) |
| latency probe | `RTKLIB=/home/tim/RTKLIB bash ./loop_latency.sh 90` — no vehicle, prints the loop delay |
| `LEN` | **211** — the rung that generalises: a 2 m quantum, so bounded error against any base. 212 was a 512 m quantum that happened to land on 2.4 m against the old base |
| vertical | measured, and it is a **negative**: a 1.12 m height lie moved the aircraft 0.04 m, because EKF3 takes height from the baro (`EK3_SRC1_POSZ`). Control step 0.000 m. The attack is horizontal-only on this airframe |
| attack trigger | `$T/attack.go`, created by the flight driver at phase 2. Replaced the `DELAY` timer, which raced the takeoff |
| speed check | `MODE=speed RTKLIB=/home/tim/RTKLIB bash ./loop_latency.sh 45` — no vehicle; feeds a 1 m/s ramp, prints the ground speed the RMC reports |
| `NMEA_VEL` | `1` in `loop_demo.sh` — harness formats the NMEA and derives the velocity. Unset reverts to RTKLIB's writer and the documented file/serial runs |
| `RUN` | 260 s — must outlast the whole flight profile or SITL loses its GPS mid-flight |
| ports | 5901 base, 5902 rover, 5911 relay, 5903 NMEA, 5760 SITL SERIAL0, 5762 SERIAL1 |
| base ECEF | `-3978243.8000,3382841.1715,3649902.7667` — sited 1.80 m above the 2 m lattice point so `n1=211` is visible. Not `-3978243.9998`: 0.2 mm from the boundary would collapse to ~0 under any sub-mm shift. The old `-3978242.4348` gives 0.43 m at 211 |
| scratch | `/tmp/rtk-loop` (logs: `sim.log`, `relay.log`, `rtklib.log`, `mavpos.log`, `sitl.log`, `flight.log`) |

Two environment traps worth remembering:

- `pkill -f <pattern>` matches the invoking `bash -lc '...'` command line
  itself if the pattern appears in it, so an ad-hoc cleanup command can kill its
  own shell and exit silently.
- `$VAR` does not survive `wsl.exe -- bash -lc '...'` from Git Bash. Use
  explicit paths or a script file, and `MSYS_NO_PATHCONV=1` for `/mnt/...`
  arguments.

## Standing caveats

- The harness derives its own GPS velocity by differencing, standing in for
  Doppler. Estimator parameters are stock now, but the *receiver* is doing
  something a real one would not have to.
- **No receiver firmware binary examined.** Emlid Reach's *source* is confirmed
  affected (`./check_fork.sh emlid/RTKLIB reach`), but the shipped firmware was
  not obtainable. Say "the source is affected", not "the product behaves this
  way".
- **ARM: measured for fortification, unconfirmed for offsets.** Debian's armhf
  binaries are unfortified, so ARM builds ship in the silent column. But
  `offsetof(sta_t,pos)` on ARM has not been checked, and that is what a payload
  length for an ARM target depends on. `check_fork.sh` computes it from a
  header; it has only been run against x86-64 assumptions.
- Windows measurement covers the decode and coordinate corruption, not the
  real-time adoption — the GUI apps were not driven.
- The vertical result is specific to a multirotor with a barometer. A vehicle
  that fuses GPS height should be expected to move in all three axes; untested.
- The demo base is *sited* so the `n1=211` rung is visible (1.80 m of a 2 m
  quantum). At an arbitrary base the error is a uniform draw in [0, 2) m. The
  bound is the claim, not the 1.8.
- **Deployed configurations are unmeasured.** The config survey covers the
  example files in the source tree only. What RTKNAVI's GUI selects on a fresh
  install, what demo5 ships, and what Emlid Reach's web UI configures are all
  unchecked — and they are what a claim about real receivers would rest on.

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
