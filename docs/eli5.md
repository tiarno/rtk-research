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

And the length number is a **dial**. Erase a little, small lie. Erase a lot,
obvious garbage that gets rejected. The attack lives in the narrow band where
the lie is small enough to be believed.

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
warning, no log entry, no crash.

**5. The autopilot is handed that position as an ordinary GPS feed.**
The GPS software emits standard GPS sentences over a serial cable. The flight
controller reads them exactly as it would from any receiver. It has no idea
anything unusual is upstream — it just sees a healthy, high-confidence fix.

**6. The drone flies to the wrong place.**
Given a position error of this size, an autopilot:

- while **hovering**, physically flew **1.9 metres sideways** — correcting a
  drift that never happened
- when told to **fly to a specific coordinate**, went to a spot **1.9 metres
  away from it, and reported that it had arrived**

A machine that is confidently wrong is more dangerous than one that knows it is
broken. Two metres is several crop rows, half a road lane, or the difference
between the landing pad and what's beside it.

---

## Which software is affected

This depends on a detail nobody thinks about: whether the program was built
with a particular safety check switched on.

- **Safety check on** — the program detects the overflow and **dies**. One
  message kills the receiver. Bad, but loud and obvious.
- **Safety check off** — the position is corrupted **silently**. This is the
  dangerous one.

We checked the actual programs people download and run. The official Windows
RTKLIB tools — including RTKNAVI, the main real-time application — are built
**without** the check. So is the popular "Demo5" fork used by most hobbyists.
Both contain the vulnerable code.

**The silent version is the normal case, not the exotic one.** You only get the
loud crash if you compile it yourself on Linux.

Worth noting: Demo5 released a new version **13 days after this bug was made
public**, and it still contains it. The original project hasn't been updated
since 2020.

Nor is a fix coming. The bug reports have sat open and unanswered since June
2026 — the person who reported them offered to file the paperwork for an
official vulnerability ID and got no reply. "Wait for the patch" is not advice
that means anything on a project nobody is maintaining.

## What is new here

A security firm (FuzzingLabs) found and reported the overflow in June 2026.
That part is theirs, and they described it accurately.

What they did not chase is **where the spillover lands**. Their own test used a
field that stops short of the coordinates. This work found the fields that
reach them, that erasing acts as a tunable dial, that the receiver swallows the
result while still claiming a perfect fix, which real builds are vulnerable in
which way — and what an aircraft then does about it.

## What is not proven

No real GPS hardware and no real aircraft were involved. This is all software
on a laptop.

**Steps 1–5 were measured as one continuous run.** A real malicious message
goes into the real GPS software, over a real serial link, and a wrong position
comes out the far side as standard GPS sentences that a flight controller
accepts and locks onto.

**Step 6 is the one to be careful about.** The 1.9 metre figures above come
from a separate test, in which the flight simulator is *given* a position error
of that size rather than receiving it from the GPS software.

The two halves have since been joined. The simulated aircraft's own position is
turned into satellite measurements, fed to the GPS software, and the answer
handed back to the aircraft as its only GPS — so the aircraft flies on a
position it computed from the attacker's message. In that setup a drone armed,
took off, flew and landed while its GPS was lying to it by the injected two
metres, and the lie arrived only as one extra message on the correction link.
Nothing was fed in by hand.

**But how far that drone ended up from where it should be is not yet a usable
number.** Our test rig has a lag in it: the aircraft's position takes too long
to travel around the loop and come back as GPS. That lag on its own makes the
aircraft wobble, and the wobble grows until it wanders off — attack or no
attack. Any distance measured that way is measuring our rig, not the attack. So
the 1.9 metre figures stand, and the closed-loop ones do not exist yet.

Two further limits. The correction link has to be carrying **this** format —
plenty of RTK radios carry a different, proprietary one, and the bug is not
reachable through those. And only a multirotor was tested, only holding
position and flying a short leg. Tractors, boats, fixed-wing aircraft and
survey workflows are untested, as is any behaviour when the error is ramped in
slowly rather than applied at once.
