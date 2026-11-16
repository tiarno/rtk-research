# RTK Research Workspace

Research on trust boundaries in RTK/GNSS positioning: *where does a
GPS-dependent system begin trusting location, how can that trust be
manipulated, and what physical or security decision follows?*

**Status, 2026-11-16.** The article is published:
[The GPS That Was Certain, and Wrong](https://reachtim.com/articles/gps-certain-and-wrong.html).
The fix is filed upstream as
[tomojitakasu/RTKLIB#801](https://github.com/tomojitakasu/RTKLIB/pull/801),
which clamps the descriptor lengths in `decode_type1033`, `1007` and `1008`.
It is open with no maintainer response, as is the original report
[#799](https://github.com/tomojitakasu/RTKLIB/issues/799). The 1033 bug is
[CVE-2026-56786](https://nvd.nist.gov/vuln/detail/CVE-2026-56786); Debian's
`rtklib` is unpatched in every release. The talk track was dropped on
2026-08-31. See [docs/HANDOFF.md](docs/HANDOFF.md).

## Current work

[research/](research/) — reproduction harness for a station-position attack on
RTKLIB's RTCM3 type 1033 decoder. A single well-formed correction message,
delivered through the real-time server, does one of two things depending on how
the binary was built:

- **fortified build** (glibc `_FORTIFY_SOURCE` at level 2 or higher actually
  reaching the compiler; level 1 does not catch it and corrupts silently,
  measured 2026-11-16) — the process aborts. Flown in the loop this is the **detectable** outcome
  (EKF failsafe 4 s after the packet, four errors logged) and a **second
  attack**: the aircraft cannot return home, so one packet sent at a moment of
  the attacker's choosing lands it ~10 m from wherever it was. Fortification is
  not a fix; it trades a silent integrity attack for a loud availability one.
  See [What the abort does to the aircraft](research/README.md#what-the-abort-does-to-the-aircraft--measured)
  and [The abort is a second attack](research/README.md#the-abort-is-a-second-attack-an-attacker-timed-forced-landing).
- **unfortified build** — the base-station coordinates shift silently. The
  receiver keeps reporting **Q=1 (RTK fixed)** while emitting a position metres
  from truth. No crash, no AddressSanitizer report, and nothing in any log
  recording that the base coordinate moved — with tracing compiled in and
  turned all the way up, all an operator gets is one line showing a
  plausible-looking antenna descriptor.

**Nearly every build measured is in the second column**, which was not the
expectation going in. The exception is Emlid's current firmware (below). Both Windows distributions (the official one and demo5)
are Embarcadero builds where the fortified `strncpy` has no equivalent to
enable, and Debian's own `rtklib` package — version 2.4.3.b34, built for 12
architectures — imports no `*_chk` at all, on ARM included. Outside Emlid,
the abort is what you get by compiling it yourself with the right flags.

The mechanism: `rectype`, the text field that gets oversized, sits 208 bytes
before `pos` in the struct (offset 256 vs. 464, fixed across every ABI
checked). Only the first 31 bytes of the declared text are ever read;
`strncpy` copies to that buffer's NUL and zero-pads the rest out to the full
declared length, so everything that reaches `pos` is padding, never attacker
content — a zeroing primitive, not an arbitrary write. The attacker chooses
the *scale* of the error, not its value: the declared length selects how many
low-order (least-significant-mantissa) bytes of the coordinate get zeroed, and
each additional byte multiplies the quantum by 256 — 8 more zeroed bits, not
one more decimal digit. The quantum at a given rung depends only on the
binary exponent of the coordinate, which rough location gives away: at
`n1=211` it is 2 m for about a third of the Earth's surface (this test base
included), 4 m for another third (|X| ≥ 2^22 m, e.g. Madrid, Lagos, Sydney),
and 1 m or finer elsewhere, down to millimetres near 90°E/W. So the attacker
needs the target's region, not its coordinates. Computed from geometry, not
measured at real stations (see the 2026-11-16 HANDOFF entry).

The source of the defect is also present unchanged in
[`emlid/RTKLIB`](https://github.com/emlid/RTKLIB) branch `reach`, the fork
Emlid describe as "used in Reach RTK receiver" — a product ArduPilot documents
as a supported RTK GPS, fed corrections over an unauthenticated radio link.
**As of 2026-08-13 this is no longer just a source-code claim for one Reach
product.** A firmware image Emlid serves publicly with no purchase or login
(Reach Plus, v2.18.1, 2019) was downloaded and its `librtk.so` — RTKLIB 2.4.3,
Emlid's own build — checked directly: the 1033 decoder is compiled in
(inlined into `decode_rtcm3`, confirmed by cross-referencing its trace
strings) and the library imports zero fortified libc symbols anywhere, so the
corruption is silent there too. **Later the same day, run rather than just
read:** `qemu-aarch64-static` (downloaded and unpacked with no root) ran
that firmware's actual `rtkrcv` binary against its own real config and a
real correction stream — its own console reported the base position moving
1.473 m, live, message counts matching exactly, nothing in the error log.
**Reach M2 and RS2, checked 2026-11-16, came out the other way.** Emlid's
firmware list (URL taken from its Linux Flash Tool) gives the full M2 release
history; 2.24.2 and 28.1 through 33.1 download publicly. Disassembly of
`reach-ublox-daemon` in eleven of them: **2.24.2 to 28.4 (to 2022-03-10)
use plain `strncpy`, silent; v29.0 (built 2022-07-14) onward use
`__strncpy_chk` with a 64-byte destination, so the attack aborts.** No
length clamp was added (checked in 33.1), so this is a build-flag change,
not a fix, and current units are the loud case. The RS2 v33.1 daemon is
byte-identical to the M2's. The original Reach RS line ends at 28.4,
unfortified. Read, not run: the M2 abort and its effect on ArduPilot are not
measured. Current Reach Plus firmware is still unchecked (not on the list
under any device name tried). See
[research/README.md](research/README.md#the-shipped-firmware-not-just-the-source)
and, for the dynamic run, "Dynamic confirmation: the shipped binary,
running, live" in the same file.

The second is a software answer to the question the project started from: can a
precision GNSS rover be manipulated while it continues to report a healthy fix?

See [research/README.md](research/README.md) for the mechanism, measured struct
offsets, the magnitude sweep, solution impact, disclosure status, and — read
these — the limitations, including which parts are not yet demonstrated
end-to-end.

## Documents

- [docs/talk-outline.md](docs/talk-outline.md) — beat sheet, demo staging, RF delivery plan, and the hardware list. **Dropped** 2026-08-31; kept as a record
- [docs/eli5.md](docs/eli5.md) — the whole thing in plain language, no GNSS background assumed
- [docs/rtk-rtklib-research-notes.md](docs/rtk-rtklib-research-notes.md) — background research, prior art, and the four disclosed decoder bugs
- [docs/rtklib-claude-code-briefing.md](docs/rtklib-claude-code-briefing.md) — original task breakdown
- [docs/rtk-delivery-path-summary.md](docs/rtk-delivery-path-summary.md) — how attacker bytes physically reach the decoder (UHF radio, NTRIP MITM, rogue caster)
- [docs/HANDOFF.md](docs/HANDOFF.md) — status notes

Note that [docs/rtklib-claude-code-briefing.md](docs/rtklib-claude-code-briefing.md)
assumes the ~191 overflow bytes can be filled with a chosen pattern. They
cannot — the write is NUL padding. That assumption is the briefing's, not
FuzzingLabs'. See
[research/README.md](research/README.md#relationship-to-the-fuzzinglabs-disclosure)
for a full reconciliation of what is theirs, what is confirmed, and what is new.

## Retired

The fork-network analysis (`rtklib_fork_network.py`, `rtklib_fork_cache.json`,
`rtklib_fork_graph.graphml`, `rtklib_seed_nodes.csv`) has been dropped. Its
headline conclusion was an artifact of an incomplete crawl, and centrality
analysis is not meaningful on a fork tree. Retained as a record of the attempt
only — do not cite figures from it. See
[docs/HANDOFF.md](docs/HANDOFF.md#network-interpretation--retracted).

## License

MIT. See [LICENSE](LICENSE).
