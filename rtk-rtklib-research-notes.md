# RTK/GNSS Attack Research — Notes for Talk Planning

*Compiled from a research conversation, July 2026. Purpose: figure out whether "RTK correction attacks" is a viable con talk angle, and if so, which specific direction is novel.*

---

## 1. Starting point

Original idea (from your GPS/PNT research summary) was framed around eleven attack surfaces in the GNSS trust chain, with **RTK correction-service attacks** flagged as the most promising: "determine whether an attacker can manipulate a precision GNSS rover while it continues reporting a healthy fix."

Central framing worth keeping regardless of which direction we land on:

> Where does a GPS-dependent system begin trusting location, how can that trust be manipulated, and what physical or security decision follows?

That's a stronger pitch than a generic SDR-spoofing demo — it's about trust boundaries, not signal theory.

---

## 2. Reality check: RF-based RTK spoofing is already published research

Searched for existing work and found a cluster of academic papers doing almost exactly the "spoof the reference station, degrade the rover" idea:

- **RTKiller** (Spanghero & Papadimitratos, KTH, ACM WiSec 2024 poster + 2024 demo paper) — spoofs the RTK *reference station* rather than the rover (much easier to capture, since it's fixed and well-located), showing the rover's solution degrades from a full RTK fix down to plain differential GNSS because the receiver tries to converge on bad corrections instead of rejecting them.
- **UnReference** (2025 follow-up, same group) — deeper analysis of the same mechanism.
- Both used proper RF simulation/replay equipment in a lab setting.

**Conclusion:** the "make a rover report a healthy fix while manipulated" demo is not novel — it's been done by a university group with real RF gear. Not a good foundation for a con talk aimed at an audience that may know this literature.

---

## 3. The better angle: RTKLIB decoder bugs (software, not RF)

Found a very recent (published June 9, 2026, updated June 16) writeup from **FuzzingLabs**: *"Spoofing the Sky: Breaking RTKLIB, the Brain Behind Centimeter-Accurate GPS"* — [fuzzinglabs.com/breaking-rtklib-gps](https://fuzzinglabs.com/breaking-rtklib-gps/)

**Why this is the stronger direction:**
- No RF hardware needed — no transmission, no legal gray zone, no anechoic chamber. Just malformed bytes over a network connection or a malicious file.
- RTKLIB is the de-facto open-source engine behind a huge swath of real RTK infrastructure — drones, survey gear, CORS networks, marine/automotive positioning — and because it's permissively licensed, it gets forked into closed firmware that never even mentions RTKLIB by name.
- The core fact is a great hook on its own, independent of the specific bugs: **no authentication, no handshake.** An attacker just needs to sit upstream of the antenna, run a rogue NTRIP caster, MITM the stream, or hand someone one booby-trapped file.

### The three data formats RTKLIB parses
| Format | Type | Carries |
|---|---|---|
| **RTCM 3.x** | Binary, real-time | Correction wire format — station coords, observations, ephemerides, SSR biases |
| **NTRIP** | Transport (HTTP-like) | How RTCM3 reaches a rover over the internet via a caster |
| **RINEX 2/3** | Text, files | Observation/navigation files distributed by CORS networks, used in post-processing |

### The four disclosed bugs (RTKLIB #796–799, coordinated disclosure, not yet public patch details as of writing)

1. **`decode_type1033`** (RTCM3, antenna/receiver descriptors) — five 8-bit attacker-controlled length fields get `strncpy`'d into fixed 64-byte buffers with no bounds check. A length of 255 writes ~191 bytes past the buffer. **Out-of-bounds WRITE** — the most interesting of the four.
   - Reach: any NTRIP/serial correction stream; base-station metadata is broadcast routinely; CRC is trivial for the sender to compute correctly.
2. **`decode_ssr3`** (RTCM3 SSR code-bias) — off-by-one array index (`mode <= ncode` should be `<`). Out-of-bounds read.
   - Reach: RTCM3 SSR streams (types 1059/1065/1242/1248/1254/1260) over NTRIP/serial.
3. **`readrnxobsb`** (RINEX **observation** file) — satellite count from the epoch header is used to write into arrays *before* it's bounds-checked. Declaring 70 sats against a 64 cap overflows the buffer.
   - Reach: a single RINEX obs file — local, emailed, or auto-fetched from a CORS FTP/HTTP mirror.
4. **`getcodepri`** (RINEX **observation** file header) — an unrecognized observation code produces a `-1` array index, reading past a string constant.
   - Reach: a crafted RINEX header with a bogus obs code.

**Note:** bugs #3 and #4 are in the RINEX **obs** file path specifically, not the nav file. Function names confirm this (`readrnxobsb` = "read RINEX obs block"; `getcodepri` resolves priority for a code listed in the obs file's header).

**Real-world impact framing** (from the FuzzingLabs piece, useful for slides):
- Boats/autonomous vessels: poisoned correction feed mid-maneuver → grounding/allision risk.
- AVs/robotics: crash the localizer → degrade or drop a safety-critical input fleet-wide (if attacking a shared caster/mountpoint).
- Drones/UAVs: corrupt the decoder on the companion computer → stall the position estimate → difference between landing and flyaway.
- Surveying/CORS: one booby-trapped RINEX file in a public dataset → quiet foothold in the geospatial supply chain.

---

## 4. Targeting: fleet-wide vs. single receiver

Question raised: the fleet-wide framing (poison a shared caster/mountpoint, everyone subscribed gets hit) is a real property of *where* you inject — not of the vulnerability itself. Narrowing to one victim:

- **RINEX file delivery is inherently single-target already** — a single file, local, emailed, or auto-fetched. Best "hit exactly one" demo: spearphish one surveyor or plant one file in a dataset they'll open.
- **MITM one specific link**, not the shared caster — rogue AP or ARP spoofing on the local segment a specific rover's companion computer sits on. NTRIP is normally unauthenticated plain HTTP-style, so on-path access to one socket only touches that one stream.
- **Redirect one device to a rogue caster** — via config tampering or targeted DNS spoofing against just that device's resolver. Serve clean data to everyone except the fingerprinted victim.
- **Attack the local/serial link** instead of network — compromised telemetry radio or malicious inline UART tap between antenna and flight/drive computer. No network exposure at all, touches exactly one machine.

**Framing for the talk:** blast radius is a property of *where in the trust chain* you inject, not of the vulnerability. Attack the caster/mountpoint → fleet. Attack a file, a link, or a device's config → exactly one. Good structure for a demo progression: start broad (poison a mountpoint), then narrow (single spearphished RINEX file to one target).

---

## 5. Nav file / ephemeris parsing — worth fuzzing?

**Important clarification first:** ephemeris/navigation data (satellite positions + clock bias) is *not* part of the differential correction step. Every receiver needs nav data just to compute any position at all; corrections (RTCM3 obs messages, MSM, SSR biases) are the separate layer that gets rover and base-station measurements to cancel error for the centimeter-level fix. In the normal case a rover decodes ephemeris directly off the satellite broadcast, independent of whatever correction stream it's also using.

This means **"poisoning" nav data to bias position is a much harder, less clean attack** than reference-station spoofing — ephemeris carries parity/CRC checks, and subtly-wrong ephemeris next to legitimate corrections would likely surface as internal inconsistency (bad residuals, failed ambiguity resolution) rather than a clean false fix.

**But that's not what a memory-corruption bug needs.** The disclosed bugs don't require the data to represent anything physically real — the attacker never needs the data to be "valid GNSS," only valid enough to reach the decoder (pass CRC/framing checks). So the nav-decoder question isn't "can I bias position via bad ephemeris" — it's "does the nav parser have the same class of unclamped-length/unchecked-index bug, reachable for crash/memory corruption regardless of whether the ephemeris makes physical sense."

**Why it's still worth chasing:**
- Untouched ground — FuzzingLabs' disclosed set is entirely in RTCM3 correction-metadata and RINEX obs paths; nothing in nav/ephemeris decoding (worth confirming directly in source, not just inferring from the writeup's silence).
- Same bug pattern likely repeats — GPS LNAV, Galileo I/NAV/F/NAV, BeiDou D1/D2, GLONASS ephemeris are all bit-packed subframe formats with PRNs, IODC/IODE values, subframe/page IDs used as table indices or buffer offsets. Structurally similar to what produced bugs #2 and #3.
- Multiple channels carry it: RTCM3 ephemeris messages (1019/1020/1042/1046, relayed over the same NTRIP stream as corrections), RINEX nav files (same file-delivery vector as the obs bugs), and raw receiver-native decoders (UBX, SBF, OEM) pulling nav subframes off serial/telemetry links.
- Tradeoff: needs per-constellation format knowledge to build a useful seed corpus — a naive random-bytes fuzzer bounces off CRC/parity before reaching the interesting subframe-unpacking logic. Need valid seed subframes + a CRC-aware mutator.

**Bottom line:** the payoff here is DoS / memory corruption, same class as the disclosed bugs — not a stealthy false-position attack. That's fine, arguably a cleaner story for a talk than reasoning about whether fake ephemeris would survive residual checks.

---

## 6. Beyond DoS — three directions to add depth

Given spoofing is already published and decoder bugs get you DoS, three ways to push further without starting over:

### A. Is the write bug (`decode_type1033`) exploitable, not just a crash?
This is the one to chase first — deepens a bug already in hand rather than opening new surface. It's the only one of the four that's a **write**, not a read; the other three are crash/info-leak at best. Concrete next steps:
1. Determine memory layout: is `rtcm->sta` inside a heap-allocated `rtcm_t`, or a static/global struct? (RTKLIB's style suggests the latter is plausible, which would make this more tractable — fixed offsets, no heap-layout fight.)
2. Build a standalone harness linking directly against `rtcm.c`/`rtcm3.c` (not the full `rtkrcv` binary), call `decode_type1033()` on a crafted buffer, compile with ASan — get an exact report of what byte offset gets corrupted.
3. Fill the ~191 overflow bytes with a distinguishing pattern (unique byte per offset, De Bruijn-style) rather than a repeated byte, so any downstream misbehavior can be traced to its source offset immediately.
4. Check what's actually adjacent to the overflow target — another unrevalidated length/count field (chainable), a function pointer (RTKLIB's stream abstraction layer has some), or just inert telemetry (caps out at "wrong output or later crash").
5. Move to a real compiled target — cheapest: x86_64 build of `str2str`/`rtkrcv` under gdb for fast iteration. More convincing for a talk: an actual ARM target (Pixhawk/ArduPilot ties into the offensive-edge-AI project's toolkit; Emlid Reach modules are a commonly cited example of RTKLIB-derived firmware) — and check whether standard mitigations (canaries, ASLR, NX) are even present, since embedded GNSS firmware likely skews toward none of these.
6. Time-box this. "Confirmed corrupted state with attacker-chosen bytes, here's the effect on reported position/fix status" is still a strong, honest finding if full control-flow hijack doesn't pan out — don't treat full exploitation as required for the talk to work.

### B. Fail-open vs. fail-closed at the application layer
Untested by anyone in the published research, because it's not a GNSS bug at all — it's the layer just past it. When RTKLIB crashes or reports garbage, does the consuming system fail safely (drone RTLs, tractor autosteer disengages, vessel holds station) or does it fail open and keep acting on stale/garbage position? Cheap to demo once you already have the crash primitive — you're just instrumenting what happens next. Strongest possible illustration of the trust-chain framing: it's the literal last link (application logic → physical action).

### C. Supply-chain mapping
Nobody has published which real consumer/commercial products embed a vulnerable RTKLIB fork. FuzzingLabs explicitly notes the flaws ride quietly into closed firmware that never says the word RTKLIB. This is a fingerprinting exercise — binary-diffing known RTKLIB decode-function signatures against firmware images of real drones/survey/ag equipment — not new bug-hunting, but it's what turns "theoretical vulnerability" into "here's the actual blast radius."

---

## 7. Open items / next steps

- [ ] Read RTKLIB source directly (not just the writeup) to confirm nav/ephemeris decoders are genuinely untouched by the disclosed bugs, and to check `rtcm->sta`'s actual allocation (heap vs. static).
- [ ] Build the ASan harness for `decode_type1033` and determine what's adjacent to the overflow.
- [ ] Decide on a target device (x86_64 build for fast iteration vs. real ARM/Pixhawk/Emlid target for talk credibility).
- [ ] If pursuing nav-decoder fuzzing: build seed corpora per constellation (GPS LNAV, Galileo I/NAV/F/NAV, BeiDou D1/D2, GLONASS) and a CRC-aware mutator.
- [ ] Confirm whether FuzzingLabs' bugs are patched yet / get a read on responsible-disclosure timeline before presenting, to avoid presenting still-open 0-days irresponsibly.
- [ ] Fail-open/fail-closed testing plan for at least one consuming application (sim first — ArduPilot SITL is a reasonable starting point per the original research summary's "recommended lab approach").

---

*Reminder from the original research summary: start without transmitting RF at all — USB/embedded receivers, virtual serial ports, generated/mutated NMEA/RTCM data, `gpsd`, receiver config tools, ArduPilot SITL. All of the above (decoder fuzzing, obs/nav file crafting, fail-open testing) fits entirely within that no-RF lab setup.*
