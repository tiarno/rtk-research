# Talk outline

> **STATUS: contingent, not a plan of record.** As of 2026-07-31 no talk is
> committed to — no CFP submitted, no venue, no deadline. This document is kept
> current because the material is ready and the outline is cheap to maintain,
> not because a talk is being prepared. The other possible output is the
> long-form article, published as [The GPS That Was Certain, and Wrong](https://reachtim.com/articles/gps-certain-and-wrong.html), which stands
> alone and does not need the talk to happen.
>
> The checklist near the end assumes an active submission. **Ignore it unless a
> talk is actually being pursued again** — its items (hardware to order, demo
> rehearsal, stage fallbacks) are only binding under a live-demo commitment.
> The authoritative record of the research itself is
> [research/README.md](../research/README.md), which is independent of both.

**Working title:** *Confidently Wrong: Moving a Drone With a Message About an
Antenna's Name*

Alternatives: *The Lie That Reports RTK FIXED* · *Two Metres, No Alarms* ·
*Nobody Checks the Base Station*

**Format:** 45 min + Q&A. A 25-minute cut is marked §CUT throughout — dropping
those sections leaves the argument intact.

**Thesis in one sentence:** a precision GNSS rover can be made to emit a
position metres from truth, while reporting its highest confidence flag, using
one well-formed correction message that nothing on the link is authorised to
send — and most builds measured fail silently rather than loudly. The
exception is current Emlid M2/RS2 firmware (v29.0 onward, built July 2022),
which aborts instead — and that is a second attack, not a safe column (§5b).

**What the audience should leave able to say:** *centimetre positioning trusts
an unauthenticated broadcast, and the failure is silent by default, not loud.*

---

## Beat sheet

| # | Section | Min | Purpose |
|---|---|---|---|
| 0 | Cold open: the demo, no explanation | 2 | Buy attention |
| 1 | What RTK is, why centimetres are bought | 4 | Stakes |
| 2 | The trust boundary | 3 | The actual thesis |
| 3 | The bug: an antenna name overwrites a coordinate | 6 | Mechanism |
| 4 | The dial has four rungs | 4 | Rigour + the universal claim |
| 5 | Which builds are affected — "never on the menu" | 5 | The transferable insight |
| 6 | Is it in a product? Emlid Reach | 4 | Real-world stakes |
| 7 | **Live demo: packet to propeller** | 8 | The payoff |
| 8 | Delivering it over the air | 4 | Completes the chain |
| 9 | The vertical negative, and the defence | 3 | Bounds it + gives the fix |
| 10 | How I nearly gave the wrong talk | 4 | The differentiator §CUT |
| 11 | Disclosure, and what to actually do | 3 | Responsibility |
| 12 | Close | 1 | |

---

## 0. Cold open (2 min)

No slides. The demo already running as people settle: a map, two aircraft
icons, a big green **RTK FIXED** indicator.

The screen is deliberately stripped for this: the mechanism panel — adopted
base coordinate, injection count — is hidden until you press `M` in §7. A base
ECEF readout during the cold open *is* an explanation, and the instruction here
is not to explain yet.

Say only: *"That drone is holding position. Its GPS says it's fixed to the
centimetre. In about thirty seconds it's going to quietly move a metre and a
half, and nothing on the screen will change colour."*

Let it happen. Then start the talk. **Do not explain yet.**

---

## 1. What RTK is (4 min)

- Ordinary GNSS: a few metres. RTK: centimetres.
- How: a second receiver on a known point broadcasts "the sky is lying by
  *this* much right now." Rover subtracts it.
- Who buys it: agriculture (autosteer, spray booms), survey, construction
  machine control, drone mapping, autonomous vehicle testing.
- **The framing that matters:** nobody buys RTK to be within two metres. Two
  metres is what you get *for free*. The entire value of the product class is
  the last two metres.

## 2. The trust boundary (3 min)

- The correction stream is unauthenticated. No signature, no key, no sanity
  check on content.
- Delivery: NTRIP over the internet, or a UHF/LoRa radio link. Neither
  authenticates. TLS adoption on NTRIP casters is under 10% — cite RTK2GO's own
  documentation naming RTKLIB-class and u-blox F9 devices as the laggards.
- **The question the whole talk answers:** what is the smallest thing an
  attacker can put on that link that changes where a machine thinks it is?

## 3. The bug (6 min)

- RTCM3 type 1033 is paperwork: antenna model, receiver type, serial numbers.
- Format: one length byte, then that many characters. Length can say 255. The
  destination field is 64 bytes. **Nobody compares them.**
- Show the three lines of `decode_type1033` with the unbounded `strncpy`.
- Show `sta_t`: seven 64-byte text fields, three ints, and then — 464 bytes in —
  `double pos[3]`, the base station's own coordinates. `rectype` (the field
  that gets oversized) starts at offset 256, so the gap to `pos` is a fixed
  208 bytes on every ABI checked (x86-64, armhf, armel, arm64, riscv64, ppc64).
- **The twist:** the spill writes *zeros*, not attacker bytes. You cannot say
  "the base is at the North Pole." You can only erase. Mechanically: only the
  first 31 bytes of the declared text are ever read into the staging buffer;
  `strncpy` copies to that buffer's NUL and then zero-pads out to the full
  declared length. Everything past byte 31 is padding, not attacker content —
  that's *why* it can only erase.
- But erasing digits off a number changes it, and the result is still a
  perfectly plausible coordinate.
- Then it self-triggers: the decoder returns 5, the server dispatches 5 to the
  routine that adopts the base position into the baseline — with no validation.
  The post-processing path has a `norm()` guard. The real-time path does not.

**Slide:** the 237-byte packet (`n1=211`, measured from `gen_rtcm.py --len 211`),
whole, with the antenna-name field highlighted.
*This is the entire attack.*

## 4. The dial has four rungs (4 min)

This is where the talk earns trust by refusing an easy claim.

- Tempting story: "the length byte is a dial, turn it for any error you like."
- **False.** Each extra zeroed byte multiplies the truncation quantum by 256.
  The settings are: *millimetres, metres, kilometres, planets.*
- Show the measured table (210/211/212/213).
- The 2.4 m figure this work started with came from the 512 m rung landing well
  against one base. Against another it gave 29 m and would be thrown away.
- **The rung that matters is `n1=211`:** it zeroes four bytes of ECEF X, so the
  error is bounded by one quantum, and the quantum depends only on the binary
  exponent of X: **2 m for about a third of the Earth's surface** (this demo's
  base included), **4 m where |X| ≥ 2²² m** (Madrid, Lagos, Sydney), 1 m or
  finer elsewhere. The attacker needs the target's *region*, not its
  coordinates. Computed from geometry, not measured at real stations.
- Say plainly: attacker picks the **scale**, not the value. Direction isn't
  chosen either — truncation always moves the coordinate toward zero, so the
  resulting shift is fixed by the base's own latitude and longitude.

## 5. Which builds are affected (5 min)

The most transferable insight in the talk.

- Two outcomes depending on the build: fortified `strncpy` **aborts** (loud,
  one packet = DoS); unfortified **corrupts silently**.
- Downloaded and ran the real thing: official Windows tools, and the demo5 build
  most low-cost users run. Both wrote a base position 2.4 m from truth. Exit
  code 0.
- **The line:** this is not a safety check somebody forgot to switch on. The
  check is a glibc feature; those are Embarcadero builds against the Windows
  CRT, which import no `*_chk` at all. *It was never on the menu.*
- **Then the part I got wrong.** I expected Linux to be the safe side. Debian
  ships RTKLIB 2.4.3 b34 for **12 architectures** — and the armhf build imports
  no `*_chk` either. On ARM. From a distribution whose policy is to enable it.
- **Conclusion, stronger for having been surprised:** the abort is what you get
  by compiling it yourself with `_FORTIFY_SOURCE=2` or higher (level 1 still
  corrupts silently). Of everything measured, **one** vendor line ships that
  way: Emlid M2/RS2 firmware from v29.0 (built 2022-07-14) onward imports
  `__strncpy_chk`; 2.24.2–28.4 do not. No length clamp was added, so it is a
  build-flag change, not a fix. Say exactly that: what changed and when, never
  why.
- **Then invert it, and land §5 on this — with the table, not an argument.**
  The instinct in the room will be that the crash column is the bad one. Both
  columns are now flown, same aircraft, same profile, same `n1=211`, differing
  only in the build (measured 2026-07-31):

  | | fortified (aborts) | unfortified (most builds measured) |
  |---|---|---|
  | GPS status | RTK FIXED → **none**, 87.5 s | **RTK FIXED the whole flight** |
  | errors logged | 4 | **0** |
  | failsafe | EKF variance → **auto LAND**, 4.0 s after GPS loss (~8 s after the packet; ArduCopter then holds 4 s before descending) | **none** |
  | outcome | on the ground 33 s after GPS loss (~37 s after the packet), 0.5 m/s | flew the leg, **reported arrival, 1.4 m from truth** |

  **The build that crashes gives the vehicle something to act on. The silent
  builds give it a confident wrong answer and nothing to trigger on.**
  - Scope it honestly if pressed: ArduCopter 4.7.0, EKF3, stock failsafe
    params, one airframe. The direction is the claim; the seconds are
    illustrative.

## 5b. …and then take the comfort away (3 min)

Do **not** let §5 land as "so compile it properly and you're fine." That is the
wrong lesson and someone will leave with it. Turn immediately:

- One line from the crashed aircraft's log does the work:
  **`SmartRTL deactivated: bad position`**. No position means it cannot fly
  home. Landing where it stands is not a choice, it is the only option.
- **So who picks the moment? The attacker does.** One packet, whenever they
  like, and the aircraft comes down near wherever it was. That is a
  denial-of-flight primitive with attacker-chosen timing — and the *unfortified*
  build cannot do it.
- **Measured** (`land_drift.py`, same run): 15 m hover, 29 s descent,
  **10.13 m of horizontal drift** between GPS loss and touchdown, monotonic —
  it slides one way and never comes back. So the attacker picks a **circle of
  tens of metres**, not a point.
  - Works: a lake, a river, a field, the far side of a fence.
  - Doesn't: a lane of traffic, a specific roof.
  - **10 m is the floor** — zero wind, low hover, near-stationary. Say this
    before anyone asks.
- Recoverable by a live pilot (non-GPS modes still fly, alarms fire).
  Unrecoverable on an autonomous BVLOS flight.

**The slide to end on — two weapons, no safe column:**

| | unfortified (most builds measured) | fortified (current Emlid M2/RS2, or `_FORTIFY_SOURCE=2`) |
|---|---|---|
| effect | position error | forced landing |
| precision | exact | ~10 m and up |
| magnitude | ~2 m before it degrades | total |
| detectable | **no** | yes |
| good for | corrupting survey/agriculture/landing quietly | taking an aircraft down on cue |

- **The line:** *"if what you want is a drone in a lake, the hardened build is
  the better tool."* Hardening swaps a silent integrity attack for a loud
  availability one. **It is not a fix. The fix is the five-line clamp.**
- *Possible demo beat:* this is a second, cheaper live run — no RF needed, and
  it ends with the aircraft landing itself instead of flying to the wrong place.
  Consider it as the fallback demo if the RF path is unreliable on the floor.

## 6. Is it in a product? (4 min)

- Everything so far is software on a laptop. Fair challenge: *is this in a
  device?*
- `emlid/RTKLIB`, branch `reach` — Emlid's own words: "used in Reach RTK
  receiver." The defect is there unchanged. Same layout, so **the same payload
  works byte-for-byte**. The unvalidated adoption is there too, inlined.
- Reach is survey-grade kit people buy. ArduPilot documents it as a supported
  drone GPS: serial to the flight controller, corrections over the telemetry
  radio.
- **Updated 2026-08-13 — this is no longer just source.** Emlid serves
  firmware images publicly, no purchase needed. Downloaded Reach Plus
  (RS+/M+) v2.18.1, opened the disk image with no root (`dd` + `debugfs`),
  and found `librtk.so` — RTKLIB 2.4.3, Emlid's own build. The 1033 decoder
  is compiled in (inlined into the dispatcher, confirmed by tracing its
  trace-string references in the disassembly) and the library imports zero
  fortified libc symbols. Same result as everything else measured: silent
  corruption, on an actual shipped product's actual firmware.
- **Same day, later — watched it happen, not just read it.** Ran that exact
  binary under `qemu-aarch64-static` (no root: downloaded as a `.deb`,
  unpacked with `dpkg-deb -x`), against its own real config and a real
  correction stream. Its own console: base position moved 1.473 m, live,
  message counters matching exactly what was sent, nothing in the error log.
  Full account: `research/README.md`, "Dynamic confirmation."
- **Scripted and rehearsed as of the same day, `research/reach_qemu_demo.sh`
  — one command, ~30 s, same clean before/after readout on every run
  checked so far.** This is a live-demo candidate, not just a slide: the
  decision (2026-08-13) is to run it live in §6 rather than cite it. See
  "Staging this live" below §8.
- **Be precise about what's still a limit.** That's Reach Plus, an older
  model, firmware from 2019, run under emulation rather than physical
  silicon.
- **Updated 2026-11-16 — the current line, checked, and it comes out the
  other way.** Emlid's firmware list gives the M2 release history; eleven
  versions disassembled (`research/emlid-m2/m2-bisect.tsv`). **M2/RS2 2.24.2
  to 28.4 (to 2022-03-10): plain `strncpy`, silent. v29.0 (built 2022-07-14)
  onward: `__strncpy_chk`, 64-byte destination — the attack aborts.** No
  length clamp in 33.1. The RS2 v33.1 daemon is byte-identical to the M2's.
  The abort was run: v33.1 `reach-gnss-logger` under qemu survives a 64-byte
  `rectype` and aborts (exit 134) at 65. **Not run:** the daemon that feeds
  the flight controller, ArduPilot's reaction on real Reach hardware, and
  RS2+ at all. Say "current M2/RS2 firmware aborts in the decoder, measured
  under emulation; older Reach firmware corrupts silently" — not "Reach is
  hacked," and not "Emlid fixed it."
- **Say plainly what this isn't.** No mass-market camera drone (DJI, Skydio,
  the thing most of the room pictures when they hear "drone") runs RTKLIB —
  different stack, and where they do RTK it's on-chip in the receiver
  silicon, a different code path this bug never touches. That's a permanent
  limit, not a hedge.
- **Say plainly what it is instead.** RTKLIB is the de-facto open engine
  behind a lot of unglamorous real RTK infrastructure that gets forked into
  closed firmware without ever using the name — precision-ag autosteer,
  survey/construction stakeout, marine autopilots, RTK mapping drones via
  Reach. Blast radius is a property of *where in the trust chain* you inject
  — a shared NTRIP mountpoint or CORS caster is fleet-wide; a single device's
  correction link is one target. Not the drone in the room's head. Not
  nothing, either.
- **Added 2026-08-13 — anticipate "what about military drones, like
  Ukraine's."** Same test as the DJI line: does the platform run RTKLIB and
  take corrections over a link an attacker can reach. Strike/FPV drones
  (kamikaze quads, loitering munitions) mostly fail that test on both counts
  — the operational trend there is *away* from live RTK links, not toward
  them, because a wireless correction stream is one more thing for EW to
  kill; fiber-optic control, inertial dead-reckoning, and terminal image
  matching exist precisely to avoid depending on RF in that environment.
  Where it plausibly does reach into a conflict zone is the same civilian
  niche this section already names, relocated: RTK-tagged demining/UXO
  survey and damage-assessment mapping drones, running the same Reach-class
  hardware as a farm survey, just operated by a military engineering unit.
  Framing for the room: not "military drones are also vulnerable" (unverified,
  overclaims), but "this doesn't touch strike drones — they've moved away
  from live RTK for the same EW reasons that make this bug interesting
  elsewhere; where it does reach a conflict zone is the boring stuff,
  demining and mapping survey, running the exact same stack as Iowa."
  Not independently verified against any specific platform — reasoning from
  the same trust-chain test above, not a new finding.

## 6b. The cheapest way onto real hardware §CUT

Added 2026-08-13, prompted by the obvious follow-up to §6, then overtaken by
events twice in one day. Originally framed around "buying a Reach M2
(~$750–1,023) is the only path that names a specific commercial product's
shipped firmware" — that premise didn't survive the morning: the actual
Reach Plus firmware turned out to be a free download. Then this section's
own reason for existing — "closes the dynamic-vs-static gap, nobody's run
this code and watched it happen on ARM" — didn't survive the afternoon
either: `qemu-aarch64-static` (downloaded as a `.deb` and unpacked with
`dpkg-deb -x`, no root, no install) ran the actual Reach Plus `rtkrcv`
binary against the actual malicious stream, and its own console reported
the base position moving by 1.473 m, live. See §6 and
`research/README.md`, "Dynamic confirmation." What's below is now a record
of the AgOpenGPS dead end and a narrower remaining case for Tier 0/1 — not
"the only way to see this dynamically" any more.

**Dead end, checked and ruled out: AgOpenGPS / any `str2str`-based tractor
setup.** The obvious "cheap tractor monitor" candidate — real farmers, real
autosteer, commonly paired with RTKLIB's `str2str` to relay NTRIP corrections
to the receiver. Read `str2str.c`/`streamsvr.c`: it only calls
`input_rtcm3()` — the vulnerable decode path — when a stream converter is
built, and that only happens if the `-out` argument carries an explicit
`#format` tag. The standard relay invocation
(`str2str -in ntrip://… -out serial://…`, no `#` suffix) never touches the
decoder — it's a transparent byte pipe, format-agnostic by design. Rigging a
`#rtcm3` tag on to force it would be demoing a configuration nobody actually
runs. Not a real-world instance of this bug.

**What does exercise it for real: `rtkrcv` / RTKNAVI — RTKLIB's own
positioning engines**, because fully parsing RTCM3 into `sta_t` is their
actual job, not incidental. Debian/Raspbian's `apt install rtklib` package
is still only confirmed unfortified **statically** (`research/README.md`,
"the distro package is unfortified too" — absent `_chk` symbols in the
`.deb`, never run). Reach Plus's own `rtkrcv`, by contrast, has now been run
— under emulation, not on physical silicon, see §6 — so the one thing left
that neither the firmware download nor the qemu run touched is *Debian's
package, or any ARM binary, actually executing on real physical hardware*.
That's a narrower, lower-priority gap than it was this morning.

| tier | hardware | cost | what it proves |
|---|---|---|---|
| 0 | `rtkrcv`/RTKNAVI on a laptop already owned + a cheap USB GPS dongle (VK-172, u-blox 7, ~$10) for genuine satellite lock | ~$10 | real unmodified RTKLIB, real sky, corruption on real (if non-embedded) hardware |
| 1 | Raspberry Pi Zero 2 W (~$15) + microSD (~$8) + the same $10 dongle, running `apt install rtklib` | ~$35–50 | the one thing the qemu run didn't: corruption on **physical** ARM silicon, not emulated. Debian's generic package, not Reach's own binary — the qemu run already covered "Reach's own binary, dynamically" |
| 1 + HITL | Tier 1 + the Pixhawk-class flight controller already on the hardware list below (~$200) | ~$235–250 | a real autopilot device physically consuming the corrupted position — no flight, no airframe needed |
| 2 (existing) | Emlid Reach M2, ~$750–1,023 | ~$750–1,023 | *Superseded 2026-11-16:* the M2/RS2 firmware question is settled from free downloads (v29.0+ fortified, aborts; see §6). Remaining job is only physical hardware and the autopilot's reaction |

No real base station is needed at any tier — the malicious correction is
synthetic (`gen_rtcm.py`, already built), exactly as it is in every other
measurement in this project. Tier 1's remaining case is narrower than it was
when this section was written: physical silicon vs. emulated, not dynamic
vs. static — the qemu run (§6) already closed the latter for Reach Plus's
own binary, for free. Tier 2's job has also narrowed: it's no longer "get
any named product at all, dynamically confirmed," it's specifically
"confirm the current M2/RS2+ line" — Reach Plus already covers the older
one, both statically and dynamically, for free.

## 7. Live demo (8 min) — the payoff

**What runs:** `loop_demo.sh` at `n1=211`. Aircraft's true position → synthetic
observables → on-path relay splices the malicious 1033 → RTKLIB solves → NMEA →
the flight controller's only GPS. Nothing fed in by hand.

**Beats, in order:**

1. **Control first, and say why.** "Any test where you can't switch the attack
   off isn't a test." Control run: arrives within **3 cm**.
2. Arm the relay. One extra message per 1005. Show the packet count climbing.
3. **The divergence.** Two icons separate on the map: truth vs. what the GPS
   claims. The gap opens to ~1.4 m.
4. **The indicator never changes.** Keep RTK FIXED on screen the whole time.
   *The drama is that nothing turns red.*
5. **The waypoint.** Commanded to a coordinate, it stops **1.39 m** away and
   reports arrival.

**Numbers on the slide:**

| | control | attacked |
|---|---|---|
| GPS vs truth | 0.00 m | 1.45 m |
| moved while holding | — | 1.36 m, *opposite* the offset |
| waypoint miss | 0.03 m | 1.39 m |

**The line for the hold:** it repositioned to correct a drift that never
happened.

**What is on the screen, and when:**
- Left pane 50 m across — carries the 30 m waypoint leg. Right pane 6 m across,
  centred on where the GPS *claims* to be — carries the metre. Neither pane
  moves or rescales at any point; the aircraft's true position slides off the
  centre of the right pane and that displacement is the whole story.
- Press `M` at the start of this section to reveal the mechanism panel: the base
  coordinate jumping `-3978243.8000` → `-3978242.0000`, and the 1033 count
  climbing. That is the cause on screen beside an indicator that never changes.
- The FIXED badge is the GGA quality field read off the wire, not a graphic.
  If somebody asks, `nmea_solq[]` in `solution.c` maps `SOLQ_FIX` to 4.

**Staging requirements — do not skip:**
- Start `demo_view.py` and open the page **before** launching the run. The
  "held for N s" counter starts when the page connects, and the trails want the
  whole flight.
- Pre-build binaries; pre-warm ports; rehearse a *failed* start.
- Fallback is `--replay` on a recorded run — the same renderer, so it looks
  identical, which is the point. Say so if you use it. **Copy the recording out
  of `$T` before you travel:** every run truncates `view.jsonl`, so the first
  live attempt on stage destroys the fallback you were relying on.
- Do **not** run the length sweep live — the four-rung reality reads as a broken
  dial. Pre-record it.
- Total runtime 260 s. Talk over it; don't watch it in silence.

## 8. Delivering it over the air (4 min)

Everything above is over a wire. This is what closes it — and how to do it
without breaking anything.

**Why the attack is radio-friendly:** it is *additive*. You are not jamming, not
suppressing the real base, not rewriting its stream. You transmit one extra
well-formed message into the gaps. 237 bytes at `n1=211` — about 0.25 s at
9600 bps. The
legitimate link keeps working, which is exactly why nothing notices.

**Persistence:** the real base re-sends 1005 every few seconds, which repairs the
coordinate. So hold the lie by re-sending after each repair — a few extra
antenna messages a minute, unremarkable on a link already carrying corrections.

### Path A — LoRa (the Emlid path, and the cheap one)

Reach uses LoRa for base↔rover: **902–928 MHz** (US) / **863–870 MHz** (EU).
That is an SX1262, the same chip as the Heltec V3 boards already on the bench.

To inject you must match: frequency, spreading factor, bandwidth, coding rate,
sync word, and preamble length. All are readable from the Reach UI, and all are
in the RadioLib API. Then transmit a packet whose payload is the RTCM3 1033
frame. The rover's radio demodulates it like any other packet and hands it to
the decoder.

**Built and measured, not just planned — separate repo, `esp32-rtcm-injector`.**
Two Heltec V3s, one running a serial-controlled TX firmware, one running the
RX counterpart. The real attack frame (a legit 1005 establishing the true
base position, then the malicious 1033) went out over real LoRa RF and was
captured byte-perfect on the second board. Those captured bytes were fed
into RTKLIB's own unmodified decoder (the same `input_rtcm3()` used
everywhere else in this talk, not a reimplementation) and `sta.pos`
corrupted from `-2694685.4730` to `-2694684.0000` — the exact `n1=211`
number from §4's table, over the air instead of a wire.

**One packet-size gotcha worth knowing before building the slide:** the
malicious 1033 frame at the demo-max length (255) is 281 bytes — LoRa's hard
payload limit is 255, so it **does not fit in a single packet.** `n1=211`
does (237 bytes) — which is also already the rung this talk recommends (§4),
so this isn't a new constraint, just a reason to be sure the slide uses 211
and not 255 for the over-the-air version specifically.

**What this validates, and what it doesn't yet.** Proven: real RF delivery
into real RTKLIB, corrupting the stored coordinate by the predicted amount.
Not yet done: this hasn't been stitched into the same continuous run as the
wire-based full chain (§7's demo) — no autopilot has flown on a position
that arrived over this radio link yet, and testing so far was an **open-air
bench check** (~1 m, 2 dBm), not through the conducted coax/attenuator/
enclosure path below. That path is still the plan for anything done in
front of an audience; treat the RF proof above as "the mechanism works,"
not as "the conducted demo is ready."

### Path B — UHF transparent serial (the professional path)

Trimble TDL450, Satel 4Pro and similar: **403–473 MHz**, GMSK or 4FSK,
4800–28800 bps, presented to the receiver as a transparent serial stream. SX1262
does GFSK, so the chip is capable, but vendor framing, scrambling and FEC vary
and are the real work. **Do not claim this one until it is measured** — the
writeup already lists it as unverified, and it should stay that way on the
slide.

Note also: plenty of professional links carry Trimble CMR/CMR+ rather than
RTCM3. There is no type 1033 in CMR, so **the bug is not reachable on those
links at all.** Say so — it's the honest bound and it pre-empts the question.

### The rule: conducted, never radiated

Everything goes down coax, through attenuators, into a shielded enclosure.
Two reasons, and the first is not the interesting one:

1. 433/868/915 MHz is where real survey, agricultural and machine-control rigs
   operate. Radiating a correction message into open air can steer somebody
   else's tractor. Don't.
2. **It is also the only version that works on a conference floor.** A hall full
   of 900 MHz noise and several hundred radios is not an environment where a
   live RF link is reliable.

"No RF was transmitted into open air" is a line worth being able to say on
stage, and it costs nothing.

---

## Hardware needed

**Tier 0 — cheapest real-ARM confirmation (see §6b).** Not required for the
stage demo. **Narrower job as of 2026-08-13, later:** the dynamic-vs-static
gap this was built to close got closed for free that same day, via
`qemu-aarch64-static` against Reach Plus's own binary (§6). What's left is
physical-silicon vs. emulated — real, but a smaller claim.

| Item | Qty | ~Cost | Note |
|---|---|---|---|
| Raspberry Pi Zero 2 W | 1 | $15 | runs `apt install rtklib` — confirmed unfortified statically, and (via qemu, on Reach's own binary, not this package) dynamically too; this tier's remaining job is physical silicon specifically |
| microSD card | 1 | $8 | — |
| USB GPS dongle (VK-172, u-blox 7) | 1 | $10 | real satellite lock, no RTK capability needed — the malicious correction is synthetic either way |

**Total: ~$33**, plus the Pixhawk-class flight controller already listed in
Tier 3 (~$200) if a real device should physically consume the corrupted
position rather than just log it.

**Tier 1 — the conducted RF demo (the minimum to do §8 live).** The two
Heltec V3s and the RF mechanism they carry are done (see §8) — everything
else in this row is still not acquired, and the validation so far was
open-air bench testing, not through this conducted path. Full parts list,
specific picks and prices in [tier1-hardware.md](tier1-hardware.md) — finalised
2026-08-09, nothing ordered yet.

| Item | Qty | ~Cost | Note |
|---|---|---|---|
| Heltec WiFi LoRa 32 V3 (SX1262, 863–928 MHz) | 2 | *owned* | legitimate base + attacker — **flashed, tested, working** |
| SMA-to-SMA coax jumpers, RG316 | 4 | $20 | conducted path — **not yet acquired** |
| SMA attenuators, 30 dB and 20 dB | 2 ea | $40 | keep levels sane, prevent front-end damage — **not yet acquired** |
| SMA 50 Ω terminations | 3 | $10 | terminate unused ports — **not yet acquired** |
| 2-way SMA splitter/combiner | 1 | $25 | inject alongside the legitimate transmitter — **not yet acquired** |
| Shielded enclosure or RF-tight bag | 1 | $60–200 | the containment story — **not yet acquired** |
| RTL-SDR v4 (receive only) | 1 | $40 | prove what is on the link; safe to own and use |

**Tier 2 — hardware credibility (upgrades "simulated" to "real kit").**
Emlid pricing corrected 2026-08-08 — the ~$300 figure below was stale by a
wide margin; checked live against the Emlid store while sourcing hardware
for the `esp32-rtcm-injector` repo. Current reality made this tier
financially out of reach for now — see `esp32-rtcm-injector`'s
`docs/HANDOFF.md` for the full lineup and the pivot to validating against
real (free) RTKLIB software instead, which is what §8's over-the-air proof
above actually did. **Superseded 2026-11-16:** free firmware downloads now
settle the fortified/unfortified question for Reach Plus *and* M2/RS2 (§6).
This tier would add only physical hardware and the autopilot's reaction to a
real M2 abort; the "settles the question" rows below are kept as a record.

| Item | Qty | ~Cost | Buys you |
|---|---|---|---|
| Emlid Reach M2 (bare module, **no built-in radio**) | 1 | ~$749–1,023 | settles the fortified/unfortified question **for M2 specifically** — Reach Plus is already settled for free, M2 isn't yet — but its own matching LoRa radio accessory is discontinued; needs a 3rd-party UART radio |
| Emlid Reach RS2+ (integrated, **built-in LoRa**) | 1 | ~$2,699 | same settling, for RS2+ — the version that doesn't need a separate radio module, currently the cheapest Emlid unit with LoRa on board |
| u-blox F9P board (ArduSimple simpleRTK2B) | 1 | ~$200 | real satellites, real observations feeding RTKNAVI |
| Multi-band GNSS antenna + ground plane | 1–2 | $80–150 | needed by both of the above |
| USB-TTL serial adapters (CP2102/FT232) | 2 | $20 | tap the serial link |

**Used Reach hardware — same claim, lower price, added 2026-08-13.**
*Superseded 2026-11-16: the current-model firmware question is settled from
free downloads (§6); a used unit would add only physical hardware and the
autopilot's reaction. Kept as a record.* A used
M2/RS2+ unit is still Emlid's own firmware lineage, so it makes the same
"current-model, named commercial product" claim a new one would — cost is
the only thing that changes. (Reach Plus itself doesn't need this treatment
any more — its firmware is a free download, see §6 — but a used M2/RS2+ is
still the cheaper way to check the *currently-sold* models.) One data point:
a Reach M2 with LoRa radio and accessories listed on the Emlid Community
Forum's "For Sale" board, Feb 2026, at **$650** against a $1,200+ new-bundle
price — roughly half. eBay and the Emlid forum's marketplace are the places
to check, not general resale sites; this is specialist survey/drone gear
with a small secondary market. Two things to verify before relying on a used
unit, not just to save money:

- **Pin the firmware version, don't let it auto-update.** ReachView can pull
  a newer build the moment it's connected to Emlid's account/cloud; the
  analysis in this project is against the published source, not against
  whatever firmware happens to ship with a specific secondhand unit. Check
  the installed version before connecting it to anything that might update
  it, and treat "unverified" and "confirmed-vulnerable" as different claims
  until it's checked — same discipline as `check_binary.sh` elsewhere in this
  project.
- **Older, cheaper Emlid units are the same codebase family, and likely
  cheaper still.** Emlid's original "Reach" module and "Reach RS" stopped
  getting firmware updates after version 29 (Emlid Community Forum,
  "29 firmware version discontinues support for Reach Module and Reach RS")
  — unsupported means unwanted means cheap on the secondary market, and an
  old frozen firmware build is, if anything, *less* likely to have picked up
  any future hardening than a currently-sold unit. Pricing not checked yet;
  worth a direct look at eBay/the Emlid forum before assuming Reach M2 is the
  floor.

**This only works for Emlid specifically — it doesn't generalise to "any
cheap used GNSS receiver."** Most of the alternative brands that come to
mind (ArduSimple, SparkFun RTK Facet, similar) do RTK on-chip in u-blox
firmware; RTKLIB only enters the picture if someone separately runs it on a
companion computer, same as the Tier 0/1 Pi path — buying the receiver
used doesn't change that. Which other commercial products embed an
RTKLIB-derived engine in their *own* firmware was an open question this
project had flagged and not answered — as of 2026-08-13 it's answered for
*one* vendor (Emlid, via the free Reach Plus firmware download, see §6),
not for the category. [rtk-rtklib-research-notes.md](rtk-rtklib-research-notes.md)
item C has the update. Buying a random cheap used receiver from some other
vendor on a hunch is still a gamble unless there's an actual lead (a
teardown, a forum post, a leaked firmware image) pointing at it — the method
that worked for Emlid (search for exact firmware filenames rather than
guessing blindly, then check the vendor's own CDN for free, unauthenticated
downloads) is worth trying first before assuming a purchase is required.

**Tier 3 — nice to have, not required.**

| Item | ~Cost | Buys you |
|---|---|---|
| TinySA Ultra | $130 | see your own signal; confirm containment |
| Heltec/Ebyte SX1262 module, 433 MHz variant | $30 | Path B experiments |
| Saleae-class logic analyser | $100+ | serial framing on the receiver side |
| Pixhawk-class flight controller | $200 | hardware-in-the-loop instead of SITL |

**Flight tier — a real airframe, not SITL/HITL.** Separate track, added
2026-08-13, not part of the numbered tiers above and not required for the
stage demo. Breaks the conducted-only rule below by necessity (an aircraft in
the air can't be reached by coax) — contained instead by low TX power and
site selection. Full list, safety preconditions, and open questions in
[flight-hardware.md](flight-hardware.md). Roughly $1,630–$1,930, nothing
ordered.

**Deliberately not on the list:** any transmit-capable SDR (HackRF, PlutoSDR).
Not needed — the SX1262 boards do the job with far less chance of an accident —
and "I never owned a transmitter that could reach open air" is a cleaner thing
to be able to say.

**Minimum viable spend to add live RF: ~$155** (Tier 1 minus the boards you
already own). **To also say "real hardware, real satellites": +~$650.**

## Staging the Reach Plus demo live (§6)

Decision 2026-08-13: run it live, alongside §7 (SITL flight) and §8 (RF),
not as a slide. That makes three independent live elements in one talk —
this section is what "rehearsed, not improvised" needs to mean for the
newest one, same discipline §7 already applies to itself.

**What's already true, as of today:** `research/reach_qemu_demo.sh` is one
command, takes about 30 seconds, and has produced the identical clean
before/after readout on every run tested so far (three, all consistent).
That's a good start, not a rehearsed demo — three runs on one machine,
by the person who wrote it, is not the same bar §7 cleared before it was
called stage-ready.

**What "rehearsed" needs to mean before this goes live in front of anyone:**

- **A recorded fallback, same principle as `demo_view.py --replay`.** If the
  live run hangs or errors on stage, the recording needs to be
  indistinguishable from a live terminal — a captured session (`script(1)`
  or similar), not a video, so it can be played back in the same terminal
  window the live attempt was going to use.
- **Rehearse the failed starts, not just the happy path** — the same
  standing instruction from the 2026-08-09 session that's never been
  optional for §7. What are this demo's specific failure shapes? At least:
  a leftover `qemu`/`rtcm_stream_server.py` process from a previous run
  still holding port 9000 or 9001 (hit repeatedly while building this —
  `pkill -f qemu-aarch64-static` and `pkill -f rtcm_stream_server.py`
  before every run is currently a manual step, not automated); the
  extracted firmware or `qemu-aarch64-static` binary not being present on
  the actual demo machine (multi-GB, deliberately not checked into the
  repo — needs a "copy this onto the laptop before travelling" checklist
  item, same shape as the `view.jsonl` reminder §7 already has); and qemu
  startup being slow enough on an unfamiliar machine to blow past
  whatever timeout the script assumes.
- **Run it on the actual demo laptop, not just the machine it was built
  on.** Nothing about qemu-user emulation should be machine-specific, but
  "should be" is exactly the phrase that precedes stage failures — this
  hasn't been tried anywhere but one WSL install yet.
- **Time it precisely once rehearsed**, the way §7 has an exact 260 s
  figure — right now "about 30 seconds" is an estimate from a few runs,
  not a number to put on a slide's timing budget.

**Not yet resolved:** whether this demo needs its own visual (a terminal
window is legible on stage, but a bigger screen showing "1005... 1005...
1033 — BASE POSITION: -2694684.000" might land harder than raw console
scrollback — worth testing against §7's screen design rather than assuming
raw text is enough).

---

## 9. The vertical negative, and the defence (3 min)

- The false position is wrong in three axes. About a third of the error is
  height: the GPS told the aircraft it was 1.12 m lower than it was.
- **It moved 4 cm.** It ignored the height lie almost entirely.
- Why: the autopilot has a *second opinion* about altitude — a barometer, which
  knows nothing about GPS and which the attacker never touched. It outvotes the
  lie.
- There is no second opinion about horizontal position. Nothing else on the
  airframe knows where it is. So that part goes through unopposed.
- **The whole defence in one sentence:** *the axis with a redundant sensor
  resisted; the axis without one moved.*
- Which also bounds the attack honestly: a third of the injected error is
  wasted, and on this airframe the effect is horizontal-only.

## 10. How I nearly gave the wrong talk (4 min) §CUT

The section that separates this from a bug writeup. Tell it as failures.

- **113 metres.** The first closed-loop run had the drone wander 113 m. A
  spectacular result — and entirely my own rig. RTKLIB's real-time path reports
  no velocity, the estimator was told it was stationary mid-flight, and it
  fought itself. **With the attack switched off it wandered just as badly.**
- **The attack that started before the aircraft did.** A timer-armed injection
  raced the takeoff and won. The "displacement" was a takeoff transient anchored
  to a lie, and it had the wrong sign. Fixed by letting the aircraft say when
  it's ready, not a clock.
- **A build that silently didn't build.** The check tested whether the binary
  existed, which passes when the *old* one is still there. Cost a full flight
  and nearly the wrong conclusion.
- **A retracted finding.** An earlier claim about the fork network was an
  artifact of a truncated crawl. Withdrawn in writing.
- **And one I got wrong in this very talk's research:** I predicted Linux builds
  would abort. They don't.
- **The rule that caught all of them:** run the control. Four times something
  looked exactly like an attack effect and wasn't.

*Any test where you cannot switch the attack off is not a test.*

## 11. Disclosure, and what to do (3 min)

- FuzzingLabs found and reported the overflow, June 2026. Credit clearly. What
  they didn't chase is where the spill lands — they framed it as memory
  corruption and never mention the base coordinates; their PoC drives a field
  that can't reach them.
- **CVE-2026-56786** (VulnCheck, 2026-06-25). Issue #799 open, no maintainer
  response. Debian's tracker: `<no-dsa>`/`<postponed>`, every release
  vulnerable. Release branch untouched since 2020-12-29.
- **"Wait for the patch" is not advice on an unmaintained project.**
- Show the fix: the clamp in `decode_type1033`, `1007` and `1008`, **filed as
  PR #801** — the slide reads *"here is the fix, filed, still unmerged."*
  Re-check #801's state the week of the talk.
- For operators, in priority order:
  1. Set the base coordinate **manually** where you can — the attack needs the
     rover to take its base position from the stream. Concede the limit
     honestly: this is free for a fixed base, and not always available, because
     taking the base coordinate from the stream is part of what makes it RTK.
     Of RTKLIB's seven shipped example configs, the *one* that does real-time
     RTK is the one that sets `ant2-postype=rtcm`. It isn't an exotic setting
     somebody opted into.
  2. TLS on NTRIP where the caster offers it.
  3. Sanity-check the base coordinate against a known value. A 2 m jump in a
     station that hasn't moved since installation is trivially detectable, and
     nothing does it. **Nothing even records it** — see below.
  4. Cross-check position against any independent source — the barometer lesson
     from §9, generalised.

**The logging slide, if there's room.** RTKLIB has a trace facility, and at
maximum verbosity it logs one line per 1033: the antenna and receiver
descriptor text. But it prints the *staging buffers*, capped at 31 characters —
so a message declaring length 255 logs identically to a benign one, the
attacker picks what those 31 characters say, and the declared length appears
nowhere at any level. The routine that actually adopts the corrupted coordinate
into the baseline emits no trace at all; it increments a message counter.

*The instrument exists and it is pointed at the wrong thing* — which is a
better closing note for the defence section than "nothing is logged," and it is
the one thing on the list a vendor could fix in an afternoon.

## 12. Close (1 min)

Callback to the cold open. Re-show the frozen frame: aircraft 1.39 m off,
indicator still green, telemetry still saying *arrived*.

Press `Space` to freeze the screen **while the run is still live** — a second
or two after the chain stops, the badge correctly goes red on a stalled feed,
which destroys the one image this section needs. Frozen, it holds green for as
long as you want to stand in front of it.

*"It never said anything was wrong. It doesn't have a way to say it. A machine
that is confidently wrong is more dangerous than one that knows it's broken —
and we built an entire industry on a broadcast nobody signs."*

---

## Pre-submission checklist

- [x] File the RTKLIB patch PR (§11 slide depends on it) — PR #801, open
- [x] `offsetof(sta_t,pos)` on ARM — **464 on all six ABIs checked** (x86-64,
      armhf, armel, arm64, riscv64, ppc64), so the payload transfers unchanged.
      `research/check_offsets.py`. Strengthens §4: `n1=211` is not an x86-64
      number, it is the number
- [x] Build the demo visuals: map, two icons, persistent FIXED indicator —
      `research/demo_view.py`, verified against a live run 2026-07-27
- [x] Record the fallback demo video — *superseded, and better:* every live run
      records 10 Hz state frames, and `--replay` plays them back through the
      same renderer. Not a video, so there is no editing step to get wrong and
      it cannot drift from what the live demo looks like
- [ ] Record the length sweep (do not run live)
- [ ] **Rehearse a failed start and the recovery patter** — now the binding
      constraint. Rehearse the three specific ways the chain can be down while
      the screen still looks plausible, all hit for real on 2026-07-27: a
      leftover process holding a port (`require_port` aborts in 10 s, naming
      it); WSL killing the collector when a session closes, which presents as
      the browser refusing to connect and looks like a network fault; and a
      viewer showing the *previous* run's phase and armed state. Know what each
      looks like from the stage and what you say while fixing it
- [ ] Copy a known-good `view.jsonl` somewhere durable before travelling — the
      first live run at the venue truncates the one in `$T`
- [x] Two Heltec V3s flashed, tested against each other, and validated
      against real RTKLIB source — see §8. **Still open:** the conducted
      path itself (coax, attenuators, shielded enclosure) — not yet ordered,
      not yet bench-tested. Testing so far is open-air bench range only.
- [ ] Tier 1 conducted-path hardware (coax/attenuators/enclosure) ordered
      and bench-tested
- [ ] Decide on Tier 2: Emlid pricing checked live 2026-08-08 and came in
      far above the ~$300 this checklist assumed (M2 alone ~$749-1,023, no
      built-in radio; RS2+ with built-in LoRa ~$2,699) — parked for now,
      not a pre-submission blocker. §8's over-the-air proof already
      validates the mechanism against real RTKLIB without needing it.
- [x] Reach Plus firmware obtained (free download) and confirmed
      unfortified, both statically and dynamically — see §6 and
      `research/README.md`. **Still open, and now the binding constraint
      for this element specifically** (see "Staging the Reach Plus demo
      live" above §9): a recorded fallback session, rehearsed failed
      starts (stale port-holding processes hit repeatedly while building
      this), a run on the actual demo laptop rather than just the machine
      it was built on, and an exact timing figure to replace "about 30s"
      — none of the four done yet
- [ ] Decide the Reach Plus demo's on-screen presentation — raw terminal
      vs. something closer to §7's screen design — before rehearsal, not
      after; changing it later means re-rehearsing

## Known questions from the audience, with answers ready

| Question | Answer |
|---|---|
| "Isn't this just a crash?" | Not on most builds measured — Windows official, demo5, Debian, Reach Plus, M2/RS2 before v29.0. Show the exit-0 evidence. Current M2/RS2 firmware does abort: that's §5b. Then turn it round: the crash is the outcome you'd *want*, because the vehicle notices. Silence is the failure nothing is built to catch. |
| "Surely a crash mid-flight is worse than 2 m of error?" | Flown both. Crash: EKF failsafe in 4.0 s, auto-LAND, on the ground in 33 s at 0.5 m/s, 4 errors logged. Corruption: zero errors, RTK FIXED throughout, flew the leg and reported arrival 1.4 m off. Then §5b: the crash is worse in a different way — it's a forced landing on the attacker's schedule. |
| "So just compile it with `_FORTIFY_SOURCE`?" | No — that's §5b. You'd be trading a silent 2 m error for a forced landing within ~10 m of wherever the attacker chose. Both are attacks. The fix is the five-line clamp. |
| "How precisely can you place the forced landing?" | 10.13 m drift measured, one run, 15 m hover, **zero wind** — a floor, not a bound. Enough for a lake, not for a lane of traffic. Don't let it be quoted as ±10 m. |
| "2 metres is nothing." | Nobody buys RTK to be within 2 m. It destroys the product's entire value while reporting maximum confidence. |
| "Did you pick a lucky length?" | Yes — originally. That's §4. The demo now runs the rung whose error is bounded by one quantum anywhere: 2 m for about a third of the Earth, 4 m at most. |
| "Who actually runs RTKLIB?" | Emlid Reach, demo5 users, Debian's package on 12 architectures, RTKNAVI operators. §5 and §6. |
| "Real drones use an F9P, not RTKLIB." | Correct, and worth conceding. The F9P does RTK on-chip. Reach is the counter-example, and ArduPilot documents it. |
| "Isn't that a niche configuration?" | No. It's not the compiled default, but of the seven example configs RTKLIB ships, the only one set up for real-time RTK is the only one that enables it. Post-processing and single-point modes have no stream to take a base position from. |
| "Wouldn't it show up in the logs?" | No. Max verbosity logs 31 characters of attacker-chosen text and never the length; the coordinate adoption isn't traced at all. |
| "Did you test real hardware?" | Updated 2026-08-13, later, again. Real radios: two Heltec V3s sent the actual attack over real LoRa RF into RTKLIB's own unmodified decoder. Real firmware, statically: Reach Plus's shipped firmware, free download, unfortified. Real firmware, **dynamically**: the actual Reach Plus `rtkrcv` binary, run under `qemu-aarch64-static` against the real config and a real correction stream, its own console reporting the base position moving 1.473 m live. Current M2/RS2 firmware, read and run (logger, under qemu): v29.0+ aborts rather than corrupts. Still not done: RS2+, the M2 daemon that feeds the autopilot, and physical ARM silicon rather than emulation. Four claims now, not three — real radios, real firmware read, real firmware run (emulated), and the two that are still open. Don't blur "run" and "run on physical hardware." |
| "If you added the Pi + Pixhawk tier (§6b), doesn't that prove a real device is vulnerable?" | The dynamic case it was meant to prove is already proven — Reach Plus's own binary, run live via `qemu-aarch64-static`, see above — so this tier's remaining job shrank to one specific thing: physical ARM silicon instead of emulation. It still doesn't touch M2/RS2+. Emulation is a real gap from physical hardware, but a much smaller one than "never executed" — the instructions that ran were the actual shipped binary's, not a recompilation. Don't undersell it as "just a Pi would prove it for real" when what's missing is narrower than that now. |
| "Did you transmit?" | For the stage demo: conducted only, into a shielded enclosure, never radiated. The bench validation that proved the LoRa mechanism works at all (§8) was low-power open-air at ~1 m, 2 dBm — say so if asked specifically about that, don't let "conducted only" cover testing it didn't apply to yet. |
| "Is this a 0-day?" | No. Public since June 2026. What's new is where the spill lands and which builds fail silently. |
| "Why can't the attacker pick any error size, not just four settings?" | Because the write zeroes whole bytes of an IEEE-754 double, low end first, and each extra byte is 8 more bits — a 256x jump in the smallest change that byte can represent. Decimal digits go up by 10x; these slots go up by 256x. That's why the usable settings are millimetres, metres, kilometres, planets and nothing in between. |
