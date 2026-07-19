# Project Briefing: RTKLIB Vulnerability Research (for hacker con talk)

*Handoff context for Claude Code. This project moved here from a chat conversation that did the research/planning phase. Two files should already be in this folder: `rtklib_fork_network.py` and `rtklib_seed_nodes.csv`. This document explains what they're for and what to do next.*

---

## Goal

Researching RTK/GNSS correction-stream vulnerabilities as the basis for a hacker conference talk. The angle: instead of RF-based GPS spoofing (already published academic work — see "Prior art" below), the talk focuses on **memory-corruption bugs in RTKLIB**, the open-source library that underlies a large share of real-world RTK positioning infrastructure (drones, precision ag, survey equipment, marine navigation).

Central framing for the talk: *"Where does a GPS-dependent system begin trusting location, how can that trust be manipulated, and what physical or security decision follows?"*

---

## Background: how RTK positioning works

A rover computes a centimeter-level position fix by combining two channels:
1. **Direct GNSS broadcast** — satellites → rover antenna, unauthenticated, gives raw ranging + ephemeris (satellite position/clock data). Every receiver needs this regardless of RTK.
2. **Differential corrections** — a fixed base station (or CORS network) also receives the broadcast, computes its own observations, and sends them as **RTCM3** messages over the internet via an **NTRIP caster**, which the rover subscribes to. The rover combines its own raw measurements with these corrections to resolve the precise fix.

**Key fact for the talk:** NTRIP/RTCM3 has no authentication and no handshake. An attacker just needs to sit upstream of the antenna, run a rogue NTRIP caster, MITM the stream, or hand someone one malicious file.

---

## Prior art (already published — do NOT re-present as novel)

- **RTKiller** (Spanghero & Papadimitratos, KTH, ACM WiSec 2024) — RF-spoofs the RTK *reference station* (easier than spoofing a moving rover) so the rover's solution degrades even though it keeps trying to converge on the corrections.
- **UnReference** (2025 follow-up, same group) — deeper analysis of the same mechanism.

Both used real RF simulation/replay equipment. This is the "old ground" segment of the talk — acknowledge briefly, move on fast.

---

## The actual research angle: RTKLIB decoder bugs

Source: **FuzzingLabs**, *"Spoofing the Sky: Breaking RTKLIB, the Brain Behind Centimeter-Accurate GPS"* — published June 9, 2026 (updated June 16). https://fuzzinglabs.com/breaking-rtklib-gps/

RTKLIB parses three untrusted data formats: **RTCM 3.x** (real-time correction wire format), **NTRIP** (transport), **RINEX** (obs/nav files). Four disclosed bugs (RTKLIB GitHub issues **#796–799**, coordinated disclosure, patch status not yet confirmed — check before presenting):

| # | Function | Format | Bug type | Notes |
|---|---|---|---|---|
| 1 | `decode_type1033` | RTCM3 (antenna/receiver descriptors) | **Out-of-bounds WRITE** | 8-bit attacker-controlled length fields `strncpy`'d into fixed 64-byte buffers, no bounds check. Length=255 → ~191-byte overwrite. **Most interesting bug — only write primitive of the four.** |
| 2 | `decode_ssr3` | RTCM3 (SSR code-bias) | OOB read | Off-by-one: `mode <= ncode` should be `<` |
| 3 | `readrnxobsb` | RINEX **obs** file | OOB write | Satellite count from epoch header used before bounds-checked against 64-sat cap |
| 4 | `getcodepri` | RINEX **obs** file header | OOB read | Unrecognized obs code → `-1` array index |

Note: bugs #3/#4 are in the **observation** file path, confirmed via function names (`readrnxobsb` = "read RINEX obs block"). Nothing in the disclosed set touches **navigation**/ephemeris decoding — this is a stated open research gap (see Task 3 below).

---

## Open technical questions / tasks (in priority order)

### Task 1 — Exploitability of `decode_type1033` (highest priority, least additional research needed)

This is the only OOB **write** of the four; the others are read/crash-only. Goal: determine whether it's a controlled memory-corruption primitive or just a crash.

Steps:
1. Clone RTKLIB source (check out the version with #796 open / still unpatched — confirm current patch status first).
2. Determine whether `rtcm->sta` (the struct holding `antdes`/`antsno`, the overflow target) is heap-allocated (inside `rtcm_t`, allocated via `init_rtcm()`) or a static/global struct. This determines the whole exploitability approach — static/global is more tractable (fixed offsets, no heap-layout fight).
3. Build a standalone C harness that links directly against `rtcm.c`/`rtcm3.c` (not the full `rtkrcv` binary) and calls `decode_type1033()` on a crafted buffer. Compile with **ASan**.
4. Fill the ~191 overflow bytes with a distinguishing byte pattern (unique value per offset, De Bruijn-style) rather than a repeated byte, so any downstream misbehavior can be traced to its source offset immediately.
5. Once ASan reports the exact corrupted offset/field, determine what's actually adjacent: another unrevalidated length/count field (chainable into a second overflow), a function pointer (RTKLIB's stream abstraction layer has some), or inert telemetry data (caps out at "wrong output or later crash").
6. Move to a real compiled target for credibility: fastest iteration is an x86_64 build of `str2str`/`rtkrcv` under gdb; more convincing for the talk is an ARM target — Pixhawk/ArduPilot, or Emlid Reach (commonly cited as RTKLIB-derived firmware). Check whether standard mitigations (stack canaries, ASLR, NX) are even present — embedded GNSS firmware likely has few or none of these.
7. **Time-box this.** "Confirmed corrupted state with attacker-chosen bytes, here's the effect on position/fix status" is still a strong, honest talk finding if full control-flow hijack doesn't pan out — don't treat full exploitation as required.

### Task 2 — Fail-open vs. fail-closed testing (untested by anyone published)

When RTKLIB crashes or reports garbage, does the consuming application fail safely (drone RTLs, tractor autosteer disengages, vessel holds station) or fail open (keeps acting on stale/garbage position)? This is the last link in the trust chain (application logic → physical action) and nobody has published on it.

Approach: start in simulation, no RF needed — **ArduPilot SITL** is the natural starting point (ties into other planned edge-device/firmware work). Feed it the crash primitive from Task 1 via its simulated GPS/companion-computer link and observe what the flight controller does next.

### Task 3 — Nav/ephemeris decoder fuzzing (open territory, more speculative)

Nothing in the disclosed bug set touches nav/ephemeris decoding. Worth checking directly in source (don't just infer from the writeup's silence). Structurally, GPS LNAV, Galileo I/NAV/F/NAV, BeiDou D1/D2, GLONASS ephemeris are all bit-packed subframe formats with PRNs/IODC/IODE/subframe IDs used as table indices or buffer offsets — same bug shape as #2 and #3.

**Important clarification:** this is not "poison nav data to bias position" (much harder — ephemeris has parity/CRC checks, and a rover getting valid corrections alongside subtly-wrong ephemeris would likely show internal inconsistency rather than a clean false fix). The value here is the same bug *class* — memory corruption/crash — not a stealthy false-position attack. The attacker-supplied data doesn't need to represent anything physically real, just valid enough to pass the outer framing checks (CRC/message type).

Channels to check: RTCM3 ephemeris messages (types 1019/1020/1042/1046, relayed over the same NTRIP stream as corrections), RINEX nav files, and raw receiver-native decoders (UBX, SBF, OEM) pulling nav subframes off serial/telemetry links. A naive random-bytes fuzzer will bounce off CRC/parity before reaching interesting logic — need a corpus of valid seed subframes and a CRC-aware mutator.

### Task 4 — Supply-chain / network analysis (the two files in this folder)

Goal: map how far RTKLIB (and its bugs) actually spread — same graph-analysis methodology as other projects (extraction → graph construction → centrality analysis to find chokepoints).

- **`rtklib_fork_network.py`** — pulls the GitHub fork tree for `tomojitakasu/RTKLIB` (root repo: ~1.8k forks / ~2.9k stars) via the GitHub API, BFS's into fork-of-a-fork relationships up to depth 3, builds a `networkx` DiGraph, computes betweenness centrality to find which forks are the biggest "patch chokepoints" (i.e., if a fork never pulls an upstream fix, how much of the downstream ecosystem stays exposed). Needs a `GITHUB_TOKEN` env var (public-repo read scope) to avoid rate limiting — expect this to take a while given the graph size. Outputs a `.graphml` file for Gephi plus a console ranking.
  - **Early hypothesis to verify:** `rtklibexplorer/RTKLIB` ("Demo5" fork, optimized for low-cost u-blox receivers) already looks like the likely top chokepoint from raw star/fork counts (937 stars / 367 forks of its own) — confirm this once the script runs.
- **`rtklib_seed_nodes.csv`** — curated manual layer (can't be scraped) of known/suspected commercial products built on RTKLIB, with a `confidence` column (`verified` / `community-sourced/unverified` / `inferred`). Most product-level entries (Emlid Reach, ArduSimple, generic u-blox OEM boards) are currently unverified — that's the remaining manual research work. Treat this the same way as any advocacy-aligned/community-sourced dataset: don't present unverified rows as confirmed without spot-checking.

Setup: `pip install requests networkx --break-system-packages`

---

## Things to keep in mind while working

- **Before presenting anything as a "finding," check current patch/disclosure status** of RTKLIB #796–799 — don't present a still-open 0-day irresponsibly.
- **Scope/targeting framing matters for the talk:** attacking a shared NTRIP caster/mountpoint affects every rover subscribed to it (fleet-wide); attacking a single file, a specific network link (MITM), or a specific device's config/DNS affects exactly one target. This is a property of *where* you inject, not of the vulnerability — good structure for a demo progression (broad → narrow).
- **No RF hardware needed for any of this** — everything here is software (decoder bugs, fuzzing, graph analysis). Consistent with the original research plan's "start without transmitting RF" recommendation (USB/embedded receivers, virtual serial ports, generated/mutated NMEA/RTCM data, `gpsd`, ArduPilot SITL).
- Two separate hacker-talk projects exist in parallel — this one (RTK/RTKLIB) and a separate network-analysis talk on Flock Safety ALPR data-sharing. Keep them as distinct talks; a possible future merge point was floated (hardware-side firmware extraction toolkit overlap) but nothing decided.
