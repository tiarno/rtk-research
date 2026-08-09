# Where to submit — a review of the options

**Status: 2026-08-09. Nothing submitted. This is a reference for deciding, not
a decision.** See [talk-outline.md](talk-outline.md) for what the talk itself
looks like; this doc only covers *where it could go*.

## The short version

Two genuinely different kinds of "prestige" came up in this search, and
they pull in different directions:

- **Prestige inside the GNSS/PNT field** — the people who build and operate
  the systems this bug affects taking the finding seriously. That's ION
  (ITM/PTTI, GNSS+). Different audience, different format, higher stakes if
  it lands.
- **Prestige inside the hacker/security community** — the audience you
  already know how to write for, that already reads Black Hat Python.
  That's Ekoparty, Black Hat, DefCamp, and the rest.

Nothing forces a choice between them forever — ION doesn't preclude a hacker
con later, or vice versa, since they're different framings of the same
research. But each submission is written for its own audience, so picking
one to write first is a real decision.

---

## Summary table

| Venue | Community | When | Deadline | Status (as of 2026-08-09) | Format |
|---|---|---|---|---|---|
| **ION ITM/PTTI 2027** | GNSS/PNT industry + academia | Anaheim, Jan 25–28, 2027 | **Oct 2, 2026** | Open | Written abstract; peer-reviewed manuscript optional (due Dec 1) |
| **ION GNSS+ 2027** | GNSS/PNT industry + academia (flagship, ~2,000+ attendees) | ~Sept 2027 (2026 ed. was Orlando) | Missed for 2026 (was Mar 3); 2027 not open | Not open — watch for ~Nov/Dec 2026 | Same as above; has a dedicated "Resilient and Secure PNT" track |
| **Ekoparty 2026** | Hacker/offensive-research | Buenos Aires, Oct 7–9, 2026 | Not published, CFP is live | Open | Talk pitch, hacker-con style |
| **Black Hat Singapore 2027** | Corporate/hacker hybrid | Marina Bay Sands | Opens Aug 26 — closes Oct 16, 2026 | Opens in 17 days | Formal CFP form, briefing abstract |
| **DefCamp 2026** | Hacker/general security | Bucharest, ~late Nov 2026 | Aug 30, 2026 (round 2 of 3) | Open | Talk pitch |
| **S4x27** | ICS/OT critical infrastructure | Tampa, Feb 8–11, 2027 | Aug 31, 2026 | Open | Talk pitch, but scope is classically PLC/SCADA |
| Black Hat Asia 2027 | Corporate/hacker hybrid | Singapore, ~April 2027 | "Coming soon" | Not open | — |
| Black Hat USA 2027 | Corporate/hacker hybrid | Las Vegas, ~Aug 2027 | Historically ~Feb–May | Not open | — |
| DEF CON 35 / Aerospace Village | Hacker, aviation/space-focused | Las Vegas, Aug 5–8, 2027 | Historically ~mid-Apr–May 1 | Not open | Main CFP is competitive; Village CFP is lighter-weight |
| 40C3 | Hacker/grassroots, CCC culture | Hamburg, Dec 27–30, 2026 | Not yet announced | Not open — watch for ~Sept 2026 | Talk pitch, informal |
| Troopers 2027 | Hacker/enterprise hybrid | Heidelberg, Jun 21–25, 2027 | Not yet announced | Not open | Talk pitch |
| OffensiveCon 2027 | Deep exploit-dev | Berlin, ~mid-2027 | Not yet announced | Not open | Low topical fit — their crowd wants kernel/browser exploitation, not systems-trust arguments |

---

## ION ITM/PTTI 2027 — the intimidating one, examined

**Why it's the best match on paper.** This isn't a security conference
borrowing a GNSS bug for a war story — it's the professional body for the
field the bug is *in*. The audience is receiver manufacturers, GNSS
researchers, military PNT people, the demo5/RTKLIB user base by proxy. If the
goal is "the people who should fix this take it seriously," this is that
room, not a hacker-con approximation of it.

**What's actually intimidating about it, specifically:**
- It's a *written abstract* first, not a talk pitch — you're arguing the
  paper's contribution in prose, not selling 45 minutes of stage time.
- Peer review is *optional*, not required — check `ITM Author Resources:
  Important Dates` before assuming a full academic manuscript is mandatory.
  Presenting without the peer-reviewed manuscript track is a normal path many
  industry submissions take.
- The audience will include people who actually work with `sta_t`,
  `refpos=POSOPT_RTCM`, and RTCM3 for a living — the bar for precision is
  "does this survive someone who reads RTCM3 spec for fun," not "does this
  land with a room that's never seen a correction stream." Given how this
  repo already treats claims — measured vs. reasoned, every number checked
  against a control run — that bar is arguably *already met*. The rigor this
  project already has is the thing that's usually missing from a first ION
  submission, not the thing you'd be short on.
- Format is a technical meeting, not a stage show. No cold open, no live
  demo pacing, no "the drama is that nothing turns red." The *content* of
  §§1–9 in [talk-outline.md](talk-outline.md) carries over almost entirely;
  the *performance* of it does not.

**What it doesn't require:** a rewrite of the research. The measured tables
in [research/README.md](../research/README.md) are already in the register
this audience expects — precise, hedged where hedging is honest, numbers
sourced. The work of writing for ITM/PTTI is compression and reframing, not
new investigation.

**The honest tradeoff:** it's a slower, quieter payoff than a hacker-con
slot. No demo crowd, no immediate "here's why this matters" reaction from
peers. What it buys instead is the finding landing with people positioned to
actually act on it — which, given this project's own instinct to hold the
patch PR for a maintainer response rather than grandstand it, might be the
more consistent move.

---

## Ekoparty 2026 — the comfortable one

Open now, Oct 7–9, Buenos Aires. This is the closest cultural match to
`talk-outline.md` as written: cold open, live demo, a room that already
speaks "trust boundary" and "silent fail-open" as a native language. Strong
reputation in the global offensive-research community — this is not a
consolation prize next to Black Hat, it's genuinely well-regarded, especially
for novel vulnerability research with a working demo attached. Lowest
rewrite cost of any option on this list, since the talk is already built for
exactly this kind of room.

## DefCamp 2026 / Black Hat Singapore 2027 — the brand options

DefCamp is open now (round 2 closes Aug 30) and is a solid, well-run general
security con without much topical risk either way. Black Hat Singapore opens
in 17 days and carries the Black Hat name, which matters if brand recognition
itself is part of the goal — but Asia-edition Black Hat CFPs are reviewed by
committee against a broad field, so acceptance odds are a genuine open
question, unlike Ekoparty where the fit is closer to a known quantity.

## S4x27 — prestigious, but check the fit before writing anything

S4 is the most respected name in ICS/OT security, full stop. But their
center of gravity is PLCs, SCADA, industrial protocols — precision-ag and
survey GNSS is adjacent, not central, to that audience. Worth a submission
only if the abstract explicitly frames RTK as *cyber-physical infrastructure
integrity* rather than leaning on the drone-hacking framing that works
everywhere else. Higher rewrite cost than Ekoparty, uncertain fit payoff.

## The ones still closed for a window

40C3's CFP isn't open yet (watch `events.ccc.de` for an announcement around
September) but is worth keeping on the list — CCC's hacker-grassroots culture
is arguably a better home for this material than any corporate-branded con,
and the Dec 27–30 date means there's no rush to decide before it opens.
Everything else not open yet (Black Hat Asia/USA 2027, Troopers, OffensiveCon,
DEF CON 35) is too far out to act on today; noting them here mainly so this
list doesn't need to be rebuilt from scratch later.

---

## Nothing decided here

This doc is deliberately not a recommendation to pick one. The two real
axes are **fit** (how much rewrite the material needs) and **who the
finding needs to reach** (people who might fix RTKLIB-derived receivers, vs.
people who'll spread the word that this class of bug exists). Ekoparty
costs the least to write and lands with the audience already targeted.
ITM/PTTI costs more to write, opens in a room that can't be reached any
other way, and the deadline (Oct 2) gives about seven weeks either way.
