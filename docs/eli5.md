# Breaking centimetre GPS with a message about an antenna's name

## The setup

Normal GPS gets you within a few metres. To get centimetres, you add a second
receiver — a **base station** — bolted down somewhere whose coordinates are
known exactly. It watches the same satellites and broadcasts "GPS is lying by
*this much* right now." Your rover applies that correction and gets centimetre
accuracy.

That's how drones, tractors, survey rigs and self-driving test vehicles know
where they are.

The catch: the rover believes that broadcast completely. No password, no
signature, no sanity check.

## The bug

Part of what the base broadcasts is paperwork — "my antenna model is
TRM59800.00." The format is simple: *a number saying how many letters follow*,
then the letters.

The number can go up to 255. The box that holds the text fits 64.
**Nobody compares them.**

So the text spills out of its box and into whatever sits next to it. And a
little further along sits the base station's own coordinates.

A message about an antenna's *name* can scribble over where the base station
*is*.

## The twist

The spillover doesn't write text you choose — it writes **blanks**. You can't
make it say "I'm at the North Pole." You can only *erase*.

But erasing part of a number changes it. Erase the tail of -3978242.4348 and
you get -3978240.0000. Still a perfectly plausible coordinate — just
**2.4 metres wrong**.

And the length number is a **coarse dial** — coarser than you'd think. Each
extra letter you claim erases one more digit of the coordinate, and erasing one
more digit multiplies the damage by 256. So there is no fine adjustment: the
settings run roughly *millimetres, metres, kilometres, planets*. Two of those
are useless to an attacker and one of them is rejected.

**Why 256, and why jumps instead of a slide.** A computer doesn't store a
coordinate as decimal digits. It stores it as a short stack of eight-bit
slots, most important on top, least important on the bottom — closer to a
weird set of nesting dolls than a row of digits. Blanking the bottom slot
erases a fraction too small to see. Blank one more slot and the jump isn't
ten times bigger, the way one more decimal digit would be — it's **256 times
bigger**, because each slot is eight bits and every bit doubles the range.
The length byte doesn't choose how much to erase in decimal. It chooses how
many of these 256x slots to blank, one at a time, with nothing in between.
That's the whole reason the dial has four rungs instead of a hundred.

The useful setting is the "metres" one, and it is useful **everywhere**. It
rounds the base station's position off to a two-metre grid, so wherever the
base actually is, the lie lands somewhere under two metres — big enough to
matter to someone who paid for centimetres, small enough that nothing complains.
The attacker doesn't need to know where the base station is to get that.

(The next rung up rounds to a *five-hundred*-metre grid. Against one base
station that happened to come out at 2.4 m — which is where this work's
original headline number came from — and against another it came out at 29 m,
which any receiver throws away. That rung is luck. The two-metre rung is not,
and it is the one the demo runs on.)

---

## The attack, from packet to propeller

```
  attacker's radio  →  correction link  →  GPS software  →  autopilot  →  drone
        one 227-byte message                wrong position          wrong place
```

**1. Get onto the correction link.**
The base talks to the rover either over the internet or over a small radio,
typically 433 or 915 MHz. Neither is authenticated. On the radio path you don't
even have to interfere with the real base — you just transmit one extra message
into the gaps between its messages. Nothing is jammed, nothing is blocked, and
the legitimate signal keeps working normally.

**2. Send one message.**
227 bytes. A quarter of a second on a slow radio link. It has a valid checksum,
a valid format, and an ordinary size. Anything inspecting the link sees a
perfectly well-formed message about an antenna.

One message is enough to *cause* the error, but not always to *keep* it. The
real base station repeats its true coordinates every few seconds, which quietly
repairs the damage — so to hold the lie you send your message again after each
repair. That is still nothing special on the link: an extra antenna message
among the ordinary traffic, a few times a minute. (On builds where the message
crashes the receiver instead, once is enough.)

**3. The rover's software overwrites its own base-station coordinates.**
The oversized "antenna name" spills past its box and erases part of the number
holding the base station's position. The base is now believed to be about two
metres from where it really is.

**4. The rover's position shifts by the same amount — and says nothing.**
Every error in the base position passes straight into the rover's answer. We
watched this over 85 consecutive position fixes: the position moved by exactly
the injected amount, and the quality flags were **identical** to a clean run.
Same number of "RTK FIXED" readings, same flag at every single moment. No
warning, no crash, and nothing written down anywhere saying the base station
moved.

There is a diagnostic log you can switch on, and it is worth knowing what it
does and doesn't tell you, because it is the closest thing to a defence that
already exists. Turned all the way up, it records one line per antenna message
— and that line shows only the first 31 characters of the text, which the
attacker writes and can make look completely ordinary. The oversized number
that causes all the damage is never written down at all, and neither is the
fact that the base station's coordinates just changed. The instrument exists;
it is pointed at the wrong thing.

**5. The autopilot is handed that position as an ordinary GPS feed.**
The GPS software emits standard GPS sentences over a serial cable. The flight
controller reads them exactly as it would from any receiver. It has no idea
anything unusual is upstream — it just sees a healthy, high-confidence fix.

**6. The drone flies to the wrong place.**
An autopilot receiving that position:

- while **hovering**, physically moved **sideways** — correcting a drift that
  never happened
- when told to **fly to a specific coordinate**, stopped **short of it and
  reported that it had arrived**

How far depends on the base station, because the attacker is erasing digits off
*its* coordinates and gets whatever those digits happened to be. On the reliable
setting it is always under two metres. The runs here measured **1.4 m**, and a
larger variant of the same attack measured **1.9 m** — the same behaviour either
way, whether the error was handed to the drone directly or it worked the error
out for itself from the attacker's message.

A machine that is confidently wrong is more dangerous than one that knows it is
broken. A metre and a half is a crop row or two, a third of a road lane, or the
difference between the landing pad and what's beside it.

**One part of the lie bounced off, and it teaches the lesson.** The false
position is wrong in three directions — sideways, forwards, and *up*. About a
third of the error was in height: the GPS told the drone it was 1.1 m lower
than it really was. The drone ignored it almost completely — it moved 4 cm.

Why? Because a drone has a **second opinion about height**. It carries a
barometer, which measures air pressure and knows nothing about GPS. When the
two disagree, the barometer wins. The attacker never touched it, so the lie
about height was outvoted.

There is no second opinion about where it is *horizontally*. Nothing else on
the aircraft knows. So that part of the lie goes through unopposed — which is
exactly why the drone moved sideways and not down.

That is the whole defence in one sentence: **the direction with a backup sensor
resisted; the direction without one moved.**

---

## Which software is affected

This depends on a detail nobody thinks about: whether anything is watching the
copy that overflows.

- **Something watching** — the overflow is detected and the program **dies**.
  One message kills the receiver. Bad, but loud and obvious.
- **Nothing watching** — the position is corrupted **silently**. This is the
  dangerous one.

It is worth sitting with why the second one is worse, because the instinct is
usually the opposite — a crash sounds like the bad outcome.

We flew both. Same drone, same simulated flight, same malicious message; the
only difference was which of the two versions of the software was in the loop.

**When the software crashes**, the position simply stops arriving. The drone
noticed in **four seconds**. It announced an error, gave up on the flight it had
been told to make, switched itself into landing mode, and put itself on the
ground half a minute later at a normal, gentle descent rate. It wrote nine
separate complaints into its own log while doing it. Whatever else you want to
say about that, the machine *knew*.

**When the software corrupts the position instead**, the same drone flew the
whole route, announced that it had arrived, and shut down normally — while
sitting 1.4 metres from where it believed it was. Its log records no errors at
all. Not one. It reported the GPS as "RTK FIXED" — the best possible quality —
from takeoff to landing, without a flicker.

That is the entire point. Every machine of this kind is built for "the sensor
stopped responding." It is an expected situation with a plan attached: warn
someone, stop, land. None of them are built for "the sensor is confidently
wrong," because there is nothing to notice. No alarm can fire when every reading
looks perfect.

So the version that crashes is the *safer* one to be **detected** — and it is
the version nobody ships.

### But the crash is its own attack

That is where we first stopped, and it was too generous to the crashing version.
Look again at one line from the crashed drone's log:

> *SmartRTL deactivated: bad position*

The drone could not fly home, because it no longer knew where home was. Landing
right there was not one choice among several. It was the only thing it could do.

Now think about who decides *when* that happens. The attacker does — it happens
the moment they send the message. So an attacker who can see the drone can wait
until it is over a lake, or a river, or the far side of a fence, and then send
one message to bring it down there.

We measured how accurate that is. From a 15-metre hover the drone drifted
**about 10 metres** sideways while it came down, always in one direction, never
correcting. So the attacker gets to pick a **rough circle**, not a spot:

- **Good enough for** a lake, a river, a field, a building site — anywhere that
  is bigger than the error.
- **Not good enough for** a particular lane of traffic or a specific rooftop.
- **And 10 metres is the best case.** Our simulation had no wind at all. Real
  wind, or a higher drone, or one that was moving when it was hit, all make the
  landing spot less predictable.

A human watching can still save it — the drone flies fine by hand once you stop
asking it where it is, and the operator gets alarms. A drone flying an automated
route with nobody watching cannot be saved.

### So: two different attacks

This is the honest way to put it. The two versions do not divide into "broken"
and "fixed". They give an attacker **two different weapons**:

|  | the version everyone runs | the version that crashes |
|---|---|---|
| what it does | moves the reported position | brings the aircraft down |
| how precise | exact, attacker's choice | within about 10 metres, or worse |
| how big | small — about 2 metres before it starts looking wrong | total: it stops flying |
| can anyone tell? | **no** | yes, immediately |
| good for | ruining survey data, farm machinery, landing accuracy — quietly, for weeks | knocking an aircraft out of the sky at a chosen moment |

And the uncomfortable conclusion: **if what you want is to put a drone in a
lake, the "safe" version is the better tool for the job.** Two metres of quiet
error will not do it. A forced landing will.

Turning the safety check on does not fix this bug. It swaps a quiet attack for a
loud one. The actual fix is five lines of code, further down.

We downloaded the actual programs people run — the official Windows tools, and
the popular "Demo5" build most hobbyists use — and fed them the malicious
message. Both accepted it without complaint and wrote a base station position
2.4 metres from the truth into their own output. Nothing crashed. Every length
we tried behaved exactly as it did in our own tests, down to the last digit.

And here is the part worth understanding: **this is not a safety check somebody
forgot to switch on.** The thing that catches the overflow is a feature of the
system libraries used on Linux. The Windows builds are made with a different
compiler and different libraries, where that feature does not exist to switch
on. So for the software almost everyone actually runs, the loud version is not
an option that was declined — it was never on the menu.

We expected Linux to be the safe side of that line. It isn't. Debian — a Linux
distribution with a formal policy of turning this protection on — ships its own
copy of this software for **twelve** different processor types, and we checked
one: the protection is absent there too. So `install this from your Linux
distribution` lands in the silent column alongside the Windows downloads.

**The silent version is the normal case, not the exotic one.** The loud crash
is what you get by compiling it yourself with the right settings — not what
anybody ships.

Worth noting: Demo5 released a new version **13 days after this bug was made
public**, and it still contains it. The original project hasn't been updated
since 2020.

Nor is a fix coming. The bug reports have sat open and unanswered since June
2026 — the person who reported them offered to file the paperwork for an
official vulnerability ID and got no reply. "Wait for the patch" is not advice
that means anything on a project nobody is maintaining.

## Is this in anything you can buy?

Everything above is software you download onto a computer. The obvious question
is whether it is in any actual *device*.

It is in the source code of one. Emlid make survey-grade GPS receivers called
Reach, and they publish the code those receivers run — their own copy of this
same software. We read it. The flaw is there, untouched: the same missing
check, the same layout, so the very same malicious message works against it
without changing a single byte. And the part that takes the corrupted
coordinate and starts navigating from it is there too.

That matters because of what a Reach is plugged into. The drone autopilot
project ArduPilot documents Reach as a supported GPS: you bolt it to the
aircraft, it feeds position to the flight controller over a wire, and — in
their own words — it can take its base-station corrections over the same radio
link the drone already uses for telemetry. That is the exact chain in this
writeup, with a real product where our simulation has a stand-in, and an
unauthenticated radio link feeding it.

**Update: we did get the firmware, and for free.** Emlid publishes firmware
images for one of their receivers — an older model called Reach Plus — as a
plain download, no purchase or account needed. We downloaded it, opened it up
(the file is just a copy of the receiver's entire storage), and searched it
for the exact same program. It is in there: the same broken code, compiled
in and reachable, and none of the protection that would turn it into a loud
crash instead of a silent error. So for this specific model, the answer to
"which of the two does it do" is settled: it corrupts silently, like
everything else we tested.

That is still not the full answer. Emlid sells other, newer receivers in the
same product line — the ones the earlier version of this write-up had in
mind — and we have not checked those; only the older model.

**Second update, same day: we ran it.** Reading the program tells you what
it would do; it doesn't prove it happens. So we found a way to actually
run this exact program — the one taken from the real firmware, not a copy
we built — using a tool that lets a different kind of computer pretend to be
the chip the receiver uses. We pointed it at the real settings the receiver
ships with, sent it the same fake correction message over a small local
network connection standing in for the radio link, and then asked the
program itself, the same way an operator would, what it currently believed
the base station's position to be. It answered with a position **1.473
metres from the truth** on one axis — a live, watched, no-guessing
confirmation of the same distance this project's other measurements
predicted. Nothing crashed and nothing complained.

So: read *and* run, for the older model. Two things remain open — the
current models (M2/RS2+) aren't checked at all, and "run" here means inside
an emulator standing in for the chip, not the receiver itself powered up on
a desk. Both are worth naming precisely rather than rounding up to "the
receiver is hacked."

## What is new here

A security firm (FuzzingLabs) found and reported the overflow in June 2026.
That part is theirs, and they described it accurately.

What they did not chase is **where the spillover lands**. Their report treats
this as a memory-corruption bug and never mentions the base station's
coordinates; their own test drives a field that stops short of them. Added
here:

- **The fields that reach the coordinates.** Only three of the five can, and the
  one their proof-of-concept uses is not among them.
- **The length byte is a coarse dial** — millimetres, metres, kilometres,
  planets — and one of its settings gives an under-two-metre error against any
  base station in the world, without knowing anything about it.
- **The receiver never notices.** It reports its highest quality flag, at every
  single moment, identically to a clean run.
- **Which real builds are affected, by running them.** Everything anybody
  ships — both Windows downloads and a Linux distribution's own package, on
  ARM — corrupts the coordinate silently. The loud crash is what you get by
  building it yourself.
- **That the source runs in a product you can buy** (Emlid Reach), which
  ArduPilot documents as a drone GPS.
- **What a vehicle does about it** — measured two independent ways, including
  one where the drone computes the false position for itself from the message.
- **That the "protected" version is not protected, it is attacked differently.**
  Flying both, the crashing version brings the drone down within about 10 metres
  of wherever it was when the message arrived — at a moment the attacker picks,
  with no ability to fly home. Turning the safety check on trades a quiet attack
  for a loud one; it does not remove the bug.

## What is not proven

No real aircraft were involved, and no physical receiver was ever powered up
and attacked live. One real receiver's actual firmware was opened up and
read, *and* separately run — its own program, its own settings, actually
executing and reporting the corrupted position back — but "run" there means
inside emulation standing in for the receiver's chip, not the receiver
itself on a desk. See "Is this in anything you can buy?" above for exactly
what each of those does and doesn't settle.

**The radio hop is no longer theoretical.** Two small radios built around
the same chip Emlid Reach uses (SX1262) sent the real malicious message over
the air — one playing the attacker, one playing the rover — and the exact
bytes that arrived were fed into RTKLIB's own, unmodified decoder. The
coordinate corrupted by exactly the amount the math predicted, over a real
radio link, not a wire.

That is a separate, standalone proof, not yet joined to the rest of the
chain below. Everything from here on — the GPS software producing a
position, that position reaching a flight controller, the flight controller
acting on it — has only been measured with the malicious message delivered
over a wire, not over the air. Radio delivery and the rest of the chain are
each proven; they have not yet been proven *together*, in one continuous
run.

**Steps 1–5 were measured as one continuous run, over a wire.** A real
malicious message goes into the real GPS software, over a real serial link,
and a wrong position comes out the far side as standard GPS sentences that a
flight controller accepts and locks onto.

**Step 6 has now been measured twice, two different ways, and the answers
agree.** The first way hands the flight simulator a position error of the
measured size directly. The second closes the whole chain: the simulated
aircraft's own position is turned into satellite measurements, fed to the GPS
software, and the answer handed back to the aircraft as its only GPS — so the
drone flies on a position it worked out for itself from the attacker's message,
with nothing fed in by hand.

To know that the second one means anything, we flew it twice: once with the
attack, once with the attacker switched off and everything else identical.

| | attacker off | attacker on |
|---|---|---|
| how far the GPS was lying | 0 cm | **1.45 m** |
| moved sideways while hovering | — | **1.36 m** |
| missed the target coordinate by | **3 cm** | **1.39 m** |

Clean, the drone parks within a hand's width of where it was told to go — three
centimetres. Under attack, it stops a metre and a half away and reports that it
has arrived.

The reassuring part is a separate check run at a larger setting, where the two
quite different setups produced the same answer — not just the same distance but
the same direction, agreeing to within 5 cm north and east. Two ways of asking
the question, one answer.

**Why that "attacker off" column matters more than it looks.** The first time
this chain ran, the drone wandered 113 metres and we nearly had a spectacular
result. It was our own rig: the GPS software never reports how fast it is
moving, and the autopilot, told it was standing still while it could feel
itself moving, fought its own navigation until it lost the argument. With the
attacker switched off it wandered just as badly. Any test where you cannot
switch the attack off is not a test.

Three further limits. The autopilot runs on **stock settings**. An earlier
version of this test had to switch off one of its estimator settings to stay
stable, because of that missing speed report; that is gone, and removing it made
the clean run *better* — 4 cm instead of 9 cm. What remains is on our side of
the wire: because the GPS software reports no speed at all, our rig works one
out by comparing consecutive positions. A real receiver measures speed directly
from the Doppler shift of the satellite signals and would not need that. It is a
crutch for our test setup, not something an attacker chooses or benefits from.
The correction link also has to be carrying **this**
format: plenty of RTK radios carry a different, proprietary one, and the bug is
not reachable through those. And only a multirotor was tested, only holding
position and flying a short leg. Tractors, boats, fixed-wing aircraft and
survey workflows are untested, as is any behaviour when the error is ramped in
slowly rather than applied at once.
