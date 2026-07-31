# Talk outline

> **STATUS: contingent, not a plan of record.** As of 2026-07-31 no talk is
> committed to — no CFP submitted, no venue, no deadline. This document is kept
> current because the material is ready and the outline is cheap to maintain,
> not because a talk is being prepared. The other possible output is the
> long-form article at [blog-1033-draft.md](blog-1033-draft.md), which stands
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
send — and every build anyone actually ships fails silently rather than loudly.

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
  `double pos[3]`, the base station's own coordinates.
- **The twist:** the spill writes *zeros*, not attacker bytes. You cannot say
  "the base is at the North Pole." You can only erase.
- But erasing digits off a number changes it, and the result is still a
  perfectly plausible coordinate.
- Then it self-triggers: the decoder returns 5, the server dispatches 5 to the
  routine that adopts the base position into the baseline — with no validation.
  The post-processing path has a `norm()` guard. The real-time path does not.

**Slide:** the 227-byte packet, whole, with the antenna-name field highlighted.
*This is the entire attack.*

## 4. The dial has four rungs (4 min)

This is where the talk earns trust by refusing an easy claim.

- Tempting story: "the length byte is a dial, turn it for any error you like."
- **False.** Each extra zeroed byte multiplies the truncation quantum by 256.
  The settings are: *millimetres, metres, kilometres, planets.*
- Show the measured table (210/211/212/213).
- The 2.4 m figure this work started with came from the 512 m rung landing well
  against one base. Against another it gave 29 m and would be thrown away.
- **The rung that matters is `n1=211`:** a 2 m quantum, so the error is bounded
  under 2 m against *any* base station on Earth, knowing nothing about it.
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
  by compiling it yourself with the right flags. It is not what anybody ships.
- **Then invert it, and land §5 on this — with the table, not an argument.**
  The instinct in the room will be that the crash column is the bad one. Both
  columns are now flown, same aircraft, same profile, same `n1=211`, differing
  only in the build (measured 2026-07-31):

  | | fortified (aborts) | unfortified (ships) |
  |---|---|---|
  | GPS status | RTK FIXED → **none**, 87.5 s | **RTK FIXED the whole flight** |
  | errors logged | 4 | **0** |
  | failsafe | EKF variance → **auto LAND**, 4.0 s after the packet | **none** |
  | outcome | on the ground in 33 s at 0.5 m/s | flew the leg, **reported arrival, 1.4 m from truth** |

  **The build that crashes gives the vehicle something to act on. The build
  everyone runs gives it a confident wrong answer and nothing to trigger on.**
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

| | unfortified (ships) | fortified (DIY) |
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
- **Be explicit about the limit:** I read the source. I did not test the device.
  I could not obtain the firmware without buying one. Either it corrupts
  silently like everything else measured, or one packet knocks a survey receiver
  off the air. Both are bad; I don't know which, and I'm not guessing.

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
well-formed message into the gaps. 227 bytes — 0.24 s at 9600 bps. The
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

**This is the demo-able one.** Two Heltecs: one as the legitimate base, one as
the attacker. Add the real Reach later.

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

**Tier 1 — the conducted RF demo (the minimum to do §8 live).**

| Item | Qty | ~Cost | Note |
|---|---|---|---|
| Heltec WiFi LoRa 32 V3 (SX1262, 863–928 MHz) | 2 | *owned* | legitimate base + attacker |
| SMA-to-SMA coax jumpers, RG316 | 4 | $20 | conducted path |
| SMA attenuators, 30 dB and 20 dB | 2 ea | $40 | keep levels sane, prevent front-end damage |
| SMA 50 Ω terminations | 3 | $10 | terminate unused ports |
| 2-way SMA splitter/combiner | 1 | $25 | inject alongside the legitimate transmitter |
| Shielded enclosure or RF-tight bag | 1 | $60–200 | the containment story |
| RTL-SDR v4 (receive only) | 1 | $40 | prove what is on the link; safe to own and use |

**Tier 2 — hardware credibility (upgrades "simulated" to "real kit").**

| Item | Qty | ~Cost | Buys you |
|---|---|---|---|
| Emlid Reach M2 | 1 | ~$300 | **the actual target**; settles the fortified/unfortified question the source review could not |
| u-blox F9P board (ArduSimple simpleRTK2B) | 1 | ~$200 | real satellites, real observations feeding RTKNAVI |
| Multi-band GNSS antenna + ground plane | 1–2 | $80–150 | needed by both of the above |
| USB-TTL serial adapters (CP2102/FT232) | 2 | $20 | tap the serial link |

**Tier 3 — nice to have, not required.**

| Item | ~Cost | Buys you |
|---|---|---|
| TinySA Ultra | $130 | see your own signal; confirm containment |
| Heltec/Ebyte SX1262 module, 433 MHz variant | $30 | Path B experiments |
| Saleae-class logic analyser | $100+ | serial framing on the receiver side |
| Pixhawk-class flight controller | $200 | hardware-in-the-loop instead of SITL |

**Deliberately not on the list:** any transmit-capable SDR (HackRF, PlutoSDR).
Not needed — the SX1262 boards do the job with far less chance of an accident —
and "I never owned a transmitter that could reach open air" is a cleaner thing
to be able to say.

**Minimum viable spend to add live RF: ~$155** (Tier 1 minus the boards you
already own). **To also say "real hardware, real satellites": +~$650.**

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
- Issues open and unanswered since June 2026. Reporter offered to file for a
  CVE; no reply. Release branch untouched since December 2020.
- **"Wait for the patch" is not advice on an unmaintained project.**
- Show the fix: a five-line clamp. File the PR before the talk so the slide
  reads *"here is the fix, filed, still unmerged."*
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

- [ ] File the RTKLIB patch PR (§11 slide depends on it)
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
- [ ] Tier 1 hardware ordered and the conducted path bench-tested
- [ ] Decide: does the Reach M2 get bought before or after acceptance?

## Known questions from the audience, with answers ready

| Question | Answer |
|---|---|
| "Isn't this just a crash?" | Not on any build anyone ships. Show the exit-0 evidence. Then turn it round: the crash is the outcome you'd *want*, because the vehicle notices. Silence is the failure nothing is built to catch. |
| "Surely a crash mid-flight is worse than 2 m of error?" | Flown both. Crash: EKF failsafe in 4.0 s, auto-LAND, on the ground in 33 s at 0.5 m/s, 4 errors logged. Corruption: zero errors, RTK FIXED throughout, flew the leg and reported arrival 1.4 m off. Then §5b: the crash is worse in a different way — it's a forced landing on the attacker's schedule. |
| "So just compile it with `_FORTIFY_SOURCE`?" | No — that's §5b. You'd be trading a silent 2 m error for a forced landing within ~10 m of wherever the attacker chose. Both are attacks. The fix is the five-line clamp. |
| "How precisely can you place the forced landing?" | 10.13 m drift measured, one run, 15 m hover, **zero wind** — a floor, not a bound. Enough for a lake, not for a lane of traffic. Don't let it be quoted as ±10 m. |
| "2 metres is nothing." | Nobody buys RTK to be within 2 m. It destroys the product's entire value while reporting maximum confidence. |
| "Did you pick a lucky length?" | Yes — originally. That's §4. The demo now runs the rung that's bounded against any base. |
| "Who actually runs RTKLIB?" | Emlid Reach, demo5 users, Debian's package on 12 architectures, RTKNAVI operators. §5 and §6. |
| "Real drones use an F9P, not RTKLIB." | Correct, and worth conceding. The F9P does RTK on-chip. Reach is the counter-example, and ArduPilot documents it. |
| "Isn't that a niche configuration?" | No. It's not the compiled default, but of the seven example configs RTKLIB ships, the only one set up for real-time RTK is the only one that enables it. Post-processing and single-point modes have no stream to take a base position from. |
| "Wouldn't it show up in the logs?" | No. Max verbosity logs 31 characters of attacker-chosen text and never the length; the coordinate adoption isn't traced at all. |
| "Did you test real hardware?" | No. Say it plainly, then say exactly what *was* measured end to end. |
| "Did you transmit?" | Conducted only, into a shielded enclosure. Never radiated. |
| "Is this a 0-day?" | No. Public since June 2026. What's new is where the spill lands and which builds fail silently. |
