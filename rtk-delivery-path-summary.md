# RTK Attack Delivery Path — Research Summary

*Covers: the "is this attack actually real or just academic" question, delivery-path research findings, and the full mechanical chain from attacker position to buffer overflow.*

---

## The original concern

After working through the RTKLIB decoder bugs, exploitability questions, and fail-open testing, the question came up: is this whole line of research more of an academic exercise than something that could actually work in the field? Specifically: **how does an attacker's malicious data actually reach the RTK buffer** — is it via cellular modem, or something else?

The honest assessment at that point: the building blocks were real (documented protocol facts, real production code, physically real delivery paths), but three gaps were still open —
1. Whether the one write bug (`decode_type1033`) is exploitable past a crash
2. Whether a crash actually causes a bad real-world outcome (fail-open vs. fail-closed)
3. Whether any *specific* real product is confirmed to run the vulnerable code

The delivery-path question was flagged as the part worth researching properly rather than assuming.

---

## Delivery path research findings

### Correction to an earlier claim: NTRIP is not universally unauthenticated

Initial framing overstated "no authentication anywhere." In practice there are two real categories of NTRIP caster:
- **Open casters** — free, public, genuinely no username/password (common for government/CORS networks).
- **Closed casters** — commercial/paid services, use HTTP Basic Authentication, and increasingly offer TLS on port 443 alongside the traditional plaintext port 2101.

### The load-bearing finding: RTKLIB-class devices routinely skip TLS entirely

- A 2019 GitHub issue on `tomojitakasu/RTKLIB` (#450) reported the library failing to connect to a NASA caster that only supported HTTPS/SSL, with the open question being whether RTKLIB supports SSL at all.
- **Confirmed as a current, general pattern, not a stale bug report:** RTK2GO — a real, currently-operating public NTRIP caster — states in its own documentation that adoption of the secure NTRIP Rev2/TLS standard has been very slow (under 1 in 10 devices routinely use it), and explicitly names lower-end devices — including ones using u-blox F9 modules or open-source code such as RTKLIB — as the class that often doesn't support secure connections at all.
- This is a citable, attributable claim (the operator of live public infrastructure characterizing the ecosystem), not an inference. It also generalizes beyond RTKLIB to a large share of the cheap RTK hardware market generally (u-blox F9-based receivers).
- Why this persists: TLS support has existed in the NTRIP spec (Rev2) for over a decade; adoption still sits under 10%. This is a structural gap in the ecosystem, not a temporary one.

**Practical implication:** even where a caster offers TLS, a plaintext-only RTKLIB-based client connecting to it means the actual traffic on the wire is unencrypted — HTTP Basic Auth credentials (base64, not encrypted) and the RTCM3 stream itself are both sniffable and interceptable/modifiable by anyone on-path, regardless of what the caster itself supports.

### Two real, mainstream delivery paths (not fringe cases)

**Path A — UHF/VHF radio link (no internet involved at all).** Confirmed via multiple current vendor/industry sources as a standard, actively-sold option specifically because it avoids depending on cellular coverage — common in survey, construction, and remote/no-signal sites. Typically 410–470MHz (some 450/900MHz), range 1–5km (up to ~10km ideal line-of-sight conditions). This is the most exposed path: no caster, no internet infrastructure to compromise, just RF within range on a known frequency — a standard SDR-range attack.

**Path B — NTRIP over cellular/WiFi/Ethernet.** Two attack variants:
- **On-path MITM** of the rover's actual connection to the real caster (rogue WiFi AP, ARP spoofing on the local segment) — realistic against plaintext HTTP given the TLS-adoption gap above, no cert-pinning fight required.
- **Redirect to a rogue caster** entirely (DNS spoofing or config tampering) — the attacker doesn't need to intercept anything, they simply become the destination the rover's NTRIP client connects to.

### Where the "is this real" skepticism was right vs. wrong

- **Wrong to fully doubt the delivery path** — it's now the best-evidenced part of the whole chain. Two independently solid delivery paths (radio-in-range, MITM-of-plaintext-NTRIP) rather than one shaky assumption.
- **Right to be skeptical of the rest** — exploitability past a crash, and real-system fail-open/fail-closed behavior, remain genuinely open and unaffected by this research.

---

## The full mechanical attack chain (delivery → overflow)

**Step 1 — Getting bytes onto the wire or into the air:**
- *Path A:* transmit on the same UHF frequency as the legitimate base station, within radio range. No authentication or encryption is understood to exist at the radio layer for these link — whichever signal the rover's radio locks onto is what gets passed along.
- *Path B:* either intercept/rewrite the rover's actual TCP connection to the real caster (on-path MITM), or redirect the rover to an attacker-controlled caster (DNS/config tampering).

**Step 2 — Bytes reach RTKLIB's stream-decoding layer.** Same endpoint regardless of transport (UHF radio's serial/UART output or NTRIP TCP socket) — RTKLIB doesn't distinguish by transport at this layer, just processes an incoming byte stream labeled as corrections.

**Step 3 — Outer framing check (not authentication).** RTCM3 messages have fixed framing: preamble byte (0xD3), length field, message-type ID, payload, CRC24Q checksum. The checksum only confirms the bytes weren't corrupted in transit — it's a data-integrity check, not an authentication check. CRC24Q is a public, computable algorithm; an attacker can produce a valid checksum for any payload they choose.

**Step 4 — Dispatch to the vulnerable handler.** RTKLIB reads the message-type field and routes to the matching decoder. Setting the type to 1033 routes to `decode_type1033` — the attacker doesn't need the payload to represent a real antenna, just a value the parser will accept.

**Step 5 — The overflow itself.** `decode_type1033` takes an attacker-controlled 8-bit length byte and `strncpy`s it into a fixed 64-byte buffer with no bounds check. A length of 255 overflows ~191 bytes into adjacent memory — this is the Task 1 bug from the main briefing doc.

**Key point for the talk:** the delivery path only determines *how the bytes reach the device* — every step from Step 2 onward is identical regardless of which path was used. The vulnerability itself is transport-agnostic, which is arguably a more damning finding than any single delivery method: there is no authentication anywhere in the chain, at any layer, on any of the realistic transports.
