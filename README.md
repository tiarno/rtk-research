# RTK Research Workspace

Research on trust boundaries in RTK/GNSS positioning: *where does a
GPS-dependent system begin trusting location, how can that trust be
manipulated, and what physical or security decision follows?*

No output is committed to as of 2026-07-31 — a talk and an article are both
drafted, neither is scheduled, and nothing here is time-critical. See
[docs/HANDOFF.md](docs/HANDOFF.md#where-this-is-going).

## Current work

[research/](research/) — reproduction harness for a station-position attack on
RTKLIB's RTCM3 type 1033 decoder. A single well-formed correction message,
delivered through the real-time server, does one of two things depending on how
the binary was built:

- **fortified build** (glibc `_FORTIFY_SOURCE` actually reaching the compiler)
  — the process aborts. Flown in the loop this is the **detectable** outcome
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

**Every build measured so far is in the second column**, which was not the
expectation going in. Both Windows distributions (the official one and demo5)
are Embarcadero builds where the fortified `strncpy` has no equivalent to
enable, and Debian's own `rtklib` package — version 2.4.3.b34, built for 12
architectures — imports no `*_chk` at all, on ARM included. The abort is what
you get by compiling it yourself with the right flags, not what anyone ships.

The mechanism: `rectype`, the text field that gets oversized, sits 208 bytes
before `pos` in the struct (offset 256 vs. 464, fixed across every ABI
checked). Only the first 31 bytes of the declared text are ever read;
`strncpy` copies to that buffer's NUL and zero-pads the rest out to the full
declared length, so everything that reaches `pos` is padding, never attacker
content — a zeroing primitive, not an arbitrary write. The attacker chooses
the *scale* of the error, not its value: the declared length selects how many
low-order (least-significant-mantissa) bytes of the coordinate get zeroed, and
each additional byte multiplies the quantum by 256 — 8 more zeroed bits, not
one more decimal digit. One rung — `n1=211`, a 2 m quantum — puts the error
under 2 m against **any** base station, with no knowledge of its coordinates.

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
Reach M2 and RS2+, the currently-sold units, are still not checked. See
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

- [docs/blog-1033-draft.md](docs/blog-1033-draft.md) — long-form article for a general audience, assuming no GNSS background. **Draft, unpublished**; its publication blockers are in an HTML comment at the top of the file
- [docs/talk-outline.md](docs/talk-outline.md) — beat sheet, demo staging, RF delivery plan, and the hardware list. **Contingent** — no talk is committed to
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
