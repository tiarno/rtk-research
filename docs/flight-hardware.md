# Flight-capable airframe — real hardware, real air

Parts list for putting the attack on an actual flying aircraft, not SITL and
not bench HITL. This is new scope, added 2026-08-13 — nothing here was
planned as of the 2026-08-09 HANDOFF. It sits alongside, not inside,
[talk-outline.md](talk-outline.md#hardware-needed)'s three tiers: Tier 1
(conducted bench demo) and the HITL row in Tier 3 both stay exactly as
documented there. This is a fourth, separate track.

**Status: first draft, not finalised, nothing ordered.** Frame/FC/RC pricing
is sourced and current as of 2026-08-13; battery, charger, and mounting
hardware are commodity placeholders that haven't been individually sourced
yet.

## Why this breaks the project's own "conducted, never radiated" rule — and the plan for containing that

[talk-outline.md:343](talk-outline.md) and
[HANDOFF.md](HANDOFF.md#2026-08-09-last-research-item-closed-hardware-list-finalised-cfp-landscape-mapped)
established conducted-only deliberately: 902–928/863–870 MHz is where real
survey and agricultural RTK rigs operate, and radiating the attack risks
hitting receivers that aren't part of the demo. A real flight can't be run
over coax — the correction link has to reach an aircraft in the air. Decision
made 2026-08-13: **fly it radiated, but range-contained** — the attacker
Heltec V3 stays at the same low power already validated on the bench (~2 dBm,
per [talk-outline.md:559](talk-outline.md)) and close to the aircraft for
the attack pass, and the site is chosen specifically for having no other
LoRa/RTK traffic nearby. This is a siting and power-discipline constraint,
not a hardware one — record the chosen site and confirm (spectrum scan with
the RTL-SDR / TinySA already on the hardware list, or just local knowledge)
that it's quiet on 863–928 MHz before flying.

This does **not** relax the "no transmit-capable SDR" rule
([talk-outline.md:405](talk-outline.md)) — still no HackRF/PlutoSDR. The
Heltec V3s (already owned, already the attack hardware) are narrow-purpose:
they can only emit LoRa-format packets in the ISM band, not arbitrary
wideband signals, which is the property that made them the right choice on
the bench and is unchanged in the air.

**Safety infrastructure this requires, not optional:**

- A safety pilot with an RC link that does **not** depend on GPS in any way —
  see the ELRS 2.4 GHz pick below, clear of both the LoRa attack band and the
  telemetry band.
- Manual override (mode switch to a GPS-independent mode, e.g. Stabilize) must
  be bench/HITL-tested to actually regain control while the aircraft is being
  fed corrupted RTK data, *before* it's tried with the aircraft airborne.
- Open land, no bystanders, no property in the fall radius, away from
  controlled airspace. FAA Part 107 (or the recreational TRUST/Part 44809
  path) applies like any other UAS flight — this project doesn't change that.
- Fly the clean/control case first, same as every other measurement in this
  repo (`research/README.md`'s control-then-attacked pattern) — confirm
  normal flight and RTL/Land behavior before the first attacked pass.

## The list

| item | qty | pick | price | link |
|---|---|---|---|---|
| Airframe + FC + motors/ESCs/props | 1 | Holybro PX4 Development Kit — X500 V2, Pixhawk 6C, **433 MHz** telemetry variant | ~$533 | [Holybro](https://holybro.com/products/px4-development-kit-x500-v2) |
| RC transmitter + receiver | 1 | RadioMaster Zorro, ELRS (2.4 GHz) starter set | ~$111 | [GetFPV](https://www.getfpv.com/radiomaster-zorro-radio-controller-elrs-starter-set.html) |
| RTK rover receiver | 1 | Emlid Reach M2 (bare module — see Tier 2 in talk-outline.md) | ~$749–1,023 | Emlid store |
| Multi-band GNSS antenna + ground plane | 1 | sized for airframe mount, matches Tier 2 pick | ~$80–150 | — |
| Airborne radio bridge | 1 | one of the two already-owned Heltec V3s, wired UART to the Reach M2 | *owned* | — |
| Flight battery, 4S ~5000 mAh LiPo | 1–2 | commodity, matched to X500 V2's ESC/motor rating | ~$50 ea | — |
| LiPo balance charger | 1 | commodity | ~$50 | — |
| LiPo-safe charging/storage bag | 1 | commodity | ~$15 | — |

**Total: roughly $1,630–$1,930**, dominated by the Reach M2. The
Holybro kit's own GPS (M8N) is not RTK-capable and is superseded by the Reach
M2 as the position source ArduPilot actually reads — keep it wired as a
fallback if the airframe kit's default config expects a GPS on that port.

## Why the 433 MHz telemetry pick

The Holybro kit ships with a choice of 433 or 915 MHz SiK telemetry. 915 MHz
overlaps the US LoRa attack band (902–928 MHz) directly; 433 MHz doesn't,
and the ELRS RC link (2.4 GHz) is clear of both. Three separate RF links —
attack/correction, telemetry, RC — on three separate bands, so nothing on
the aircraft has to guess which packets belong to which system.

## What is not resolved yet

- **Reach M2 vs. RS2+, confirmed M2.** RS2+ (~$2,699, built-in LoRa) is a
  handheld/pole-mount survey unit, not built to fly. M2 is a 35 g bare OEM
  module explicitly aimed at drone integration — cheaper and the obvious
  pick once weight is a constraint. Its LoRa radio accessory being
  discontinued (per Tier 2 in talk-outline.md) is fine here: one of the
  already-owned Heltec V3s fills that role over UART, which also means the
  attack hardware and the legitimate-link hardware are the same board family
  the rest of this project already uses.
- **Wiring plan for the airborne Heltec V3 → Reach M2 UART link** — not
  drawn yet. Needs the Reach M2's serial port pinout and confirmation of
  logic-level compatibility.
- **Battery/charger/bag are placeholders** — no specific SKU chosen; sized to
  "whatever the X500 V2's stock ESCs/motors expect," not independently
  verified against Holybro's spec.
- **Site selection is not a hardware task but is a blocking one.** "Range-
  contained radiated" only holds if the flying site is actually free of other
  863–928 MHz users — needs an actual location, not just a criterion.
- **Not bench-tested, not HITL-tested, not flown.** This entire tier is
  parts-list-only. The safety-pilot manual-override validation described
  above is a precondition for the first flight, not a nice-to-have.
