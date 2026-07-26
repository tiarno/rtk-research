# RTK Research Workspace

Research toward a conference talk on trust boundaries in RTK/GNSS positioning:
*where does a GPS-dependent system begin trusting location, how can that trust
be manipulated, and what physical or security decision follows?*

## Current work

[research/](research/) — reproduction harness for a station-position attack on
RTKLIB's RTCM3 type 1033 decoder. A single well-formed correction message,
delivered through the real-time server, does one of two things depending on how
the binary was built:

- **fortified build** (glibc `_FORTIFY_SOURCE` actually reaching the compiler)
  — the process aborts. One packet is a remote DoS.
- **unfortified build** — the base-station coordinates shift silently. The
  receiver keeps reporting **Q=1 (RTK fixed)** while emitting a position metres
  from truth. No crash, no log entry, no AddressSanitizer report.

**Every build measured so far is in the second column**, which was not the
expectation going in. Both Windows distributions (the official one and demo5)
are Embarcadero builds where the fortified `strncpy` has no equivalent to
enable, and Debian's own `rtklib` package — version 2.4.3.b34, built for 12
architectures — imports no `*_chk` at all, on ARM included. The abort is what
you get by compiling it yourself with the right flags, not what anyone ships.

The attacker chooses the *scale* of the error, not its value: the declared
length selects how many low-order bytes of the coordinate are zeroed, and each
byte multiplies the quantum by 256. One rung — `n1=211`, a 2 m quantum — puts
the error under 2 m against **any** base station, with no knowledge of its
coordinates.

The source of the defect is also present unchanged in
[`emlid/RTKLIB`](https://github.com/emlid/RTKLIB) branch `reach`, the fork
Emlid describe as "used in Reach RTK receiver" — a product ArduPilot documents
as a supported RTK GPS, fed corrections over an unauthenticated radio link.

The second is a software answer to the question the project started from: can a
precision GNSS rover be manipulated while it continues to report a healthy fix?

See [research/README.md](research/README.md) for the mechanism, measured struct
offsets, the magnitude sweep, solution impact, disclosure status, and — read
these — the limitations, including which parts are not yet demonstrated
end-to-end.

## Documents

- [docs/talk-outline.md](docs/talk-outline.md) — the talk this is destined for: beat sheet, demo staging, RF delivery plan, and the hardware list
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
