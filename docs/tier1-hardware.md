# Tier 1 hardware — the conducted RF demo

Parts list for [talk-outline.md](talk-outline.md#hardware-needed)'s Tier 1 row:
the minimum to run §8 live, conducted only, never radiated. The two Heltec V3
boards (legitimate base + attacker) are already owned, flashed, and validated
against real RTKLIB — see `esp32-rtcm-injector`'s `docs/HANDOFF.md`. Everything
below is what is still needed to get from "open-air bench test" to "on a
conference table, contained."

**Status: list finalised 2026-08-09, nothing ordered yet.**

## The list

| item | qty | pick | price | link |
|---|---|---|---|---|
| RG316 SMA-M/M jumper, 50 cm | 4 | ALLiSHOP RG316, 2-pack — buy 2 packs | ~$20 | [Amazon](https://www.amazon.com/ALLiSHOP-Connector-Extension-Assembly-Equipment/dp/B08PYV8KRJ) |
| SMA attenuator, 30 dB, 10 W, DC–6 GHz | 2 | BECEN 10 W 30 dB SMA | ~$25 | [Amazon](https://www.amazon.com/BECEN-10Watt-30dB-Attenuator-6GHz/dp/B0F5VF6BCZ) |
| SMA attenuator, 20 dB, 10 W, DC–6 GHz | 2 | BECEN 10 W 20 dB SMA — same product family as the 30 dB pick, matched power rating | ~$25 | [Amazon](https://us.amazon.com/BECEN-10Watt-20dB-Attenuator-6GHz/dp/B0F5TW8PH7) |
| SMA 50 Ω termination, 1 W, DC–6 GHz | 3 | Amazon SMA-M push-on termination | ~$10 | [Amazon](https://www.amazon.com/Termination-Connector-Terminators-Antennas-Broadcast/dp/B0DFCCKQMT) |
| 2-way SMA splitter/combiner | 1 | Mini-Circuits ZFSC-2-2500-S+ (10–2500 MHz, resistive, comfortably spans 863–928 MHz) | ~$20–25 | [Mouser](https://www.mouser.com/ProductDetail/Mini-Circuits/ZFSC-2-2500-S+) |
| Containment | 1 | Mission Darkness Non-Window Faraday Bag, Tablet size (13"×9" usable, 60 dB average attenuation) | $65 | [MOS Equipment](https://mosequipment.com/products/mission-darkness-non-window-faraday-bag-for-tablets) |

**Total: ~$165–170**, against the $155 estimate in the talk outline.

## Why these picks

- **Attenuators matched in power rating and vendor family (BECEN, 10 W, both
  DC–6 GHz)** rather than mixing a lab-grade part with a budget one — one
  fewer variable if a measurement looks off on the bench.
- **Splitter is resistive (ZFSC-2-2500-S+), not Wilkinson (e.g. ZAPD-21).**
  Wilkinson splitters have better port-to-port isolation but a narrower band
  (ZAPD-21 bottoms out at 500 MHz); the resistive part's 10–2500 MHz range
  covers both US (902–928) and EU (863–870) without swapping parts, and
  isolation doesn't matter here — nothing downstream cares if a trace of the
  attacker's signal reaches the legitimate board's port, since the point of
  the demo is that it reaches the *receiver*, not that the two transmitters
  are isolated from each other.
- **Faraday bag over a machined SMA-bulkhead box.** The actual containment is
  the coax path — antennas disconnected, signal never leaves a conductor from
  TX board to attenuators to splitter to RX board. The bag is redundant
  containment and the stage prop for "no RF was transmitted into open air."
  Tablet size fits both boards plus a USB power bank; a laptop-size bag ($105)
  would be needed only if a larger control rig has to go inside too.

## What is not resolved yet

- **Confirm the splitter's actual passband before ordering** — pull the
  [ZFSC-2-2500-S+ datasheet](https://www.minicircuits.com/pdfs/ZFSC-2-2500+.pdf)
  and check insertion loss / isolation specifically at 863–928 MHz, not just
  the headline 10–2500 MHz range.
- **Termination pack size** — the linked Amazon listing's per-unit quantity
  wasn't checked; buy enough to get to 3.
- **Not yet bench-tested.** Ordering this list is necessary but not
  sufficient — [talk-outline.md](talk-outline.md#pre-submission-checklist)
  still has "Tier 1 conducted-path hardware ordered **and bench-tested**" as
  one checklist item, not two. Verifying the assembled chain (antennas off,
  full coax path, inside the bag) against the open-air bench numbers already
  recorded in `esp32-rtcm-injector` is the next step once parts arrive.
