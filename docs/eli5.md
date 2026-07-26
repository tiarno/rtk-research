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
An autopilot receiving that position:

- while **hovering**, physically moved about **two metres sideways** —
  correcting a drift that never happened
- when told to **fly to a specific coordinate**, stopped roughly **two metres
  away from it, and reported that it had arrived** (1.9 m handed the error
  directly; 1.8 m with the drone computing it from the message itself)

A machine that is confidently wrong is more dangerous than one that knows it is
broken. Two metres is several crop rows, half a road lane, or the difference
between the landing pad and what's beside it.

---

## Which software is affected

This depends on a detail nobody thinks about: whether anything is watching the
copy that overflows.

- **Something watching** — the overflow is detected and the program **dies**.
  One message kills the receiver. Bad, but loud and obvious.
- **Nothing watching** — the position is corrupted **silently**. This is the
  dangerous one.

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

What they did not chase is **where the spillover lands**. Their report treats
this as a memory-corruption bug and never mentions the base station's
coordinates; their own test drives a field that stops short of them. Added
here:

- **The fields that reach the coordinates.** Only three of the five can, and the
  one their proof-of-concept uses is not among them.
- **The length byte is a dial**, from a five-millimetre nudge to total
  destruction, and the interesting setting is the small one.
- **The receiver never notices.** It reports its highest quality flag, at every
  single moment, identically to a clean run.
- **Which real builds are affected, by running them.** The programs people
  download corrupt the coordinate silently. The loud crash only happens on a
  build almost nobody uses.
- **What a vehicle does about it** — measured two independent ways, including
  one where the drone computes the false position for itself from the message.

## What is not proven

No real GPS hardware and no real aircraft were involved. This is all software
on a laptop.

**Steps 1–5 were measured as one continuous run.** A real malicious message
goes into the real GPS software, over a real serial link, and a wrong position
comes out the far side as standard GPS sentences that a flight controller
accepts and locks onto.

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
| how far the GPS was lying | 1 cm | **2.1 m** |
| missed the target coordinate by | **9 cm** | **1.8 m** |

Clean, the drone parks within a hand's width of where it was told to go. Under
attack, it stops nearly two metres away and reports that it has arrived. That
second column is close to the 1.9 metres the separate test produced, which is
the reassuring part: two quite different setups, the same answer.

**Why that "attacker off" column matters more than it looks.** The first time
this chain ran, the drone wandered 113 metres and we nearly had a spectacular
result. It was our own rig: the GPS software never reports how fast it is
moving, and the autopilot, told it was standing still while it could feel
itself moving, fought its own navigation until it lost the argument. With the
attacker switched off it wandered just as badly. Any test where you cannot
switch the attack off is not a test.

Three further limits. To keep the closed-loop drone stable we had to switch off
one setting the autopilot normally uses, because of that missing speed report —
a workaround for our rig, not something an attacker gets to choose, and a real
receiver would not need it. The correction link also has to be carrying **this**
format: plenty of RTK radios carry a different, proprietary one, and the bug is
not reachable through those. And only a multirotor was tested, only holding
position and flying a short leg. Tractors, boats, fixed-wing aircraft and
survey workflows are untested, as is any behaviour when the error is ramped in
slowly rather than applied at once.
