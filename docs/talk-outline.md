# Talk outline

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

**Staging requirements — do not skip:**
- Pre-build binaries; pre-warm ports; rehearse a *failed* start.
- Recorded fallback ready, and say so if you use it.
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
- Show the fix: a three-line clamp. File the PR before the talk so the slide
  reads *"here is the fix, filed, still unmerged."*
- For operators, in priority order:
  1. Set the base coordinate **manually** where you can — the attack needs the
     rover to take its base position from the stream.
  2. TLS on NTRIP where the caster offers it.
  3. Sanity-check the base coordinate against a known value. A 2 m jump in a
     station that hasn't moved since installation is trivially detectable, and
     nothing does it.
  4. Cross-check position against any independent source — the barometer lesson
     from §9, generalised.

## 12. Close (1 min)

Callback to the cold open. Re-show the frozen frame: aircraft 1.39 m off,
indicator still green, telemetry still saying *arrived*.

*"It never said anything was wrong. It doesn't have a way to say it. A machine
that is confidently wrong is more dangerous than one that knows it's broken —
and we built an entire industry on a broadcast nobody signs."*

---

## Pre-submission checklist

- [ ] File the RTKLIB patch PR (§11 slide depends on it)
- [ ] `offsetof(sta_t,pos)` on ARM — cross-compile, no emulation needed
- [ ] Build the demo visuals: map, two icons, persistent FIXED indicator
- [ ] Record the fallback demo video
- [ ] Record the length sweep (do not run live)
- [ ] Rehearse a failed start and the recovery patter
- [ ] Tier 1 hardware ordered and the conducted path bench-tested
- [ ] Decide: does the Reach M2 get bought before or after acceptance?

## Known questions from the audience, with answers ready

| Question | Answer |
|---|---|
| "Isn't this just a crash?" | Not on any build anyone ships. Show the exit-0 evidence. |
| "2 metres is nothing." | Nobody buys RTK to be within 2 m. It destroys the product's entire value while reporting maximum confidence. |
| "Did you pick a lucky length?" | Yes — originally. That's §4. The demo now runs the rung that's bounded against any base. |
| "Who actually runs RTKLIB?" | Emlid Reach, demo5 users, Debian's package on 12 architectures, RTKNAVI operators. §5 and §6. |
| "Real drones use an F9P, not RTKLIB." | Correct, and worth conceding. The F9P does RTK on-chip. Reach is the counter-example, and ArduPilot documents it. |
| "Did you test real hardware?" | No. Say it plainly, then say exactly what *was* measured end to end. |
| "Did you transmit?" | Conducted only, into a shielded enclosure. Never radiated. |
| "Is this a 0-day?" | No. Public since June 2026. What's new is where the spill lands and which builds fail silently. |
