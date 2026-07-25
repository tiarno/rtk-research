# RTK Research Workspace

Research toward a conference talk on trust boundaries in RTK/GNSS positioning:
*where does a GPS-dependent system begin trusting location, how can that trust
be manipulated, and what physical or security decision follows?*

## Current work

[research/](research/) — reproduction harness for a station-position attack on
RTKLIB's RTCM3 type 1033 decoder. A single well-formed correction message,
delivered through the real-time server, does one of two things depending on how
the binary was built:

- **fortified build** (glibc `_FORTIFY_SOURCE`, the distro default) — the
  process aborts. One packet is a remote DoS.
- **unfortified build** (embedded/firmware toolchains) — the base-station
  coordinates shift silently by an attacker-chosen amount. In the small-error
  band the receiver keeps reporting **Q=1 (RTK fixed)** while emitting a
  position metres from truth. No crash, no log entry, no AddressSanitizer
  report.

The second is a software answer to the question the project started from: can a
precision GNSS rover be manipulated while it continues to report a healthy fix?

See [research/README.md](research/README.md) for the mechanism, measured struct
offsets, the magnitude sweep, solution impact, disclosure status, and — read
these — the limitations, including which parts are not yet demonstrated
end-to-end.

## Documents

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
