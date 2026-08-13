# Handoff Notes

**Session date:** 2026-08-13

## 2026-08-13: Reach Plus's actual shipped firmware obtained free, confirmed unfortified — biggest open caveat in the project resolved for one product

Session started as hardware-buying questions (Tier 1 conducted-RF list,
whether an off-the-shelf drone is affected, cheapest path onto real
hardware, used Reach M2 pricing) and ended somewhere nobody expected: asking
"could we do the supply-chain fingerprinting exercise from
`rtk-rtklib-research-notes.md` (item C)" turned up a real, unauthenticated,
free firmware download, and running it down settled the single biggest
standing caveat in the whole project — "I read the source, I did not test
the device" — for one specific Emlid product.

**What happened, in order:**

1. `files.emlid.com` returns 403 for directory listings and for every path
   guessed directly (matching the existing note in `research/README.md`).
   Search engines know exact filenames that direct guessing didn't turn up:
   `reach-plus-v2.18.1.zip`, 363 MB, downloaded clean, no auth. (`reach-m2-*`
   and `reach-rs2-*` variants were tried, guessing off the same naming
   pattern; all 403'd. Stopped there rather than keep guessing — enough
   guesses starts to look like scanning a vendor's bucket rather than
   following a lead.)
2. The zip contains a 2.19 GB Raspberry-Pi-style SD card image. No root
   needed: `fdisk -l` reads the DOS partition table straight from the file;
   `dd` carves the largest Linux partition by sector offset; `debugfs -R
   rdump` reads the ext4 filesystem without mounting. (This is exactly what
   `research/check_image.sh` already automates — see below for running it
   properly, after the fact.)
3. `usr/lib/librtk.so`: RTKLIB 2.4.3, Emlid's own build, ARM aarch64, not
   stripped. Grepping the extracted tree for the 1033 decoder's trace
   strings found it directly.
4. **No standalone `decode_type1033` symbol — initially looked like the
   message type just wasn't supported in this build.** It isn't absent: used
   Capstone (`pip install --user`, no root) to disassemble, since this
   x86_64 host's `objdump` has no AArch64 backend, and traced both trace
   strings' `.rodata` addresses back to `adrp`/`add` pairs *inside*
   `decode_rtcm3` itself. The compiler inlined it — one call site, small
   function, ordinary optimization — and the ELF symbol table only kept
   names for the `decode_typeNNNN` functions that stayed separate. The logic
   is live and reachable from an exported function.
5. `research/check_binary.sh`, run directly against the extracted
   `librtk.so`, confirms it cleanly in the project's own established format:
   `1033 decoder present : yes` / `__strncpy_chk : absent` / `any *_chk
   import : none at all` / `UNFORTIFIED: the coordinate is corrupted
   silently`. Same evidentiary bar already used for the Debian ARM package
   claim, now applied to an actual shipped product.
6. Tried pulling `offsetof(sta_t,pos)` straight from the binary's DWARF info,
   since `file` reports `with debug_info, not stripped`. Dead end: the only
   DWARF present is for the linked-in `crti.S`/`crtn.S` C-runtime stubs, not
   RTKLIB's own code. The struct-offset claim still rests on the six-ABI
   `check_offsets.py` table (which does cover arm64), not on this binary
   directly.

**Scope, stated precisely because it's easy to overstate:** this is Reach
Plus (RS+/M+), not Reach M2 or RS2+ — the currently-sold models, whose
firmware filenames weren't found. It's firmware from 2019 (v2.18.1); whether
a current build differs is unchecked. And it's static analysis — the binary
was read, not run; nobody has watched the corruption happen live on this
exact binary. All three of these are now stated explicitly everywhere the
old "I have not examined any device's firmware" caveat used to stand alone.

**Docs updated to carry this** (all in this session, this is the commit):
`README.md`, `research/README.md` (new section "The shipped firmware, not
just the source," the measured-builds table, the "not casually obtainable"
paragraph, the Limitations bullet, the reproduction command block),
`docs/talk-outline.md` (§6, §6b's premise, the Tier 2 hardware table and the
used-hardware note, two FAQ entries), `docs/eli5.md` (the product section
and "What is not proven"), `docs/blog-1033-draft.md` (a resolved publication
blocker, Part 14, Part 15), `docs/rtk-rtklib-research-notes.md` (item C
marked done for one instance).

**Not finished this session:** running `check_image.sh` itself end-to-end
against the image, for full-pipeline corroboration rather than the targeted
manual steps above. Started, but its `dd` uses `bs=512` and crossing the
WSL↔Windows filesystem boundary at that block size is extremely slow (the
same trap hit and fixed manually with `bs=1M` earlier in the session) —
still running in the background when this session ended, not blocking on
it since `check_binary.sh` against the manually-extracted library already
gives the citable, canonical result. Worth either waiting for it to finish
or fixing its block size if this comes up again.

**Artifacts, not committed:** `~/rtk-fw` (WSL, visible at
`/mnt/c/Users/tim/rtk-fw` from Windows) holds the downloaded zip, the raw
`.img`, and the extracted filesystem tree — roughly 5 GB across the manual
extraction and the `check_image.sh` run's own copy. Not in the repo, not
cleaned up yet.

**Next steps, in priority order:**

1. Same firmware-hunting approach against Reach M2 / RS2+ — the models the
   Tier 2 hardware line is actually about now. Different filename pattern;
   worth another documentation-search pass rather than more guessing.
2. Let `check_image.sh` finish (or rerun with a larger `dd` block size) for
   the full-pipeline corroboration, and consider whether the manual
   Capstone-based inlining trace is worth turning into a reusable script —
   `check_binary.sh` doesn't currently handle the "trace string present but
   no named symbol" case, and this won't be the last binary where that's
   true.
3. Try dynamic confirmation — `qemu-user` running this exact `librtk.so`
   against a crafted 1033 stream, or the Pi tier from §6b — to close the
   static-vs-dynamic gap explicitly called out above.
4. Everything from the 2026-08-09 session below is still open and unchanged
   by this one: CFP decision, Tier 1 RF hardware purchase, rehearsal.

---

**Previous session:** 2026-08-09

## 2026-08-09: last research item closed, hardware list finalised, CFP landscape mapped

No code path changed — this was a documentation, logistics and one closed-out
research session. Read every doc in the repo plus `esp32-rtcm-injector`'s
handoff to rebuild full context from scratch, then worked three threads.
**Nothing committed to git** — everything below is in the working tree.

**Research is now fully closed out.** The last open item in "Next steps,
in the order I would take them" (below) — whether `decode_type1007`/`1008`
carry the same unclamped-`strncpy` shape as 1033, and whether they reach
`sta.pos` — is answered and measured, not just argued from offsets. New
`research/check_1007_1008.py` runs both message types through the real
decoder (WSL `~/RTKLIB`, pinned `180043e`) with `antdes`/`antsno` declared at
255. Result: `sta.pos` and a `dgps` sentinel stay untouched in every case.
Both fields sit too early in `sta_t` (offsets 128 and 192) to reach `pos`
(464) or even leave the 560-byte struct. **Memory-safety only, no
positioning impact, on either type** — confirmed, matching the prediction.
Answers "why 1033?": of the five descriptor fields across all three message
types, only `rectype`/`recver`/`recsno` sit after `pos`, and all three
belong to 1033. Written up in `research/README.md` (new section, two
cross-references updated from "not examined here", Files table), plus
`harness.c` (now also dumps `antsno`/`recver`) and `gen_rtcm.py` (gained
`msg1007`/`msg1008`). **Still open, and it's a decision not a task:**
whether to file the misalignment defect as its own GitHub issue — see
"Still to do" under Disclosure timeline, below, unchanged this session.

**Chose a direction: pursue the talk** (of the two possible outputs — the
article was not touched this session). Two threads followed from that:

- **Tier 1 RF hardware finalised.** Full parts list (~$165–170) against the
  spec in [talk-outline.md](talk-outline.md#hardware-needed):
  `docs/tier1-hardware.md`, linked from the Tier 1 table there. **Nothing
  purchased** — no purchasing capability this session, and two things are
  flagged in that doc as worth checking before buying: the splitter's actual
  passband at 863–928 MHz specifically (not just its headline range), and
  the terminator listing's pack size.
- **CFP/venue landscape mapped**, broadly — roughly twenty hacker-security
  and GNSS/PNT conferences checked for live 2026/2027 CFPs as of today. Full
  comparison in `docs/cfp-options.md`. Headline finding: **ION ITM/PTTI
  2027** (Anaheim, Jan 25–28) has an open CFP, abstract due **Oct 2, 2026** —
  the strongest topical/prestige match, since it puts the finding in front of
  the actual GNSS/PNT industry rather than a hacker-con approximation of it.
  Different format though: written abstract, peer review optional. **Ekoparty
  2026** (Buenos Aires, Oct 7–9) is open now too and is the closest cultural
  fit to the talk as already built — lowest rewrite cost of any option.
  Nothing submitted, nothing decided.

**Disclosure status, live-checked this session:** `gh issue view 799` — still
**OPEN**, no maintainer reply since the 2026-07-27 comment (13 days silent as
of today), consistent with no commit to the release branch since
2020-12-29. Nothing new to act on; the patch PR is still deliberately held.

**Files changed, uncommitted:**

| file | change |
|---|---|
| `research/check_1007_1008.py` | new — measures whether 1007/1008 reach `sta.pos` |
| `research/README.md` | new section on the 1007/1008 result; two cross-references updated; Files table entry |
| `research/harness.c` | `dump_sta` now also prints `antsno`/`recver` |
| `research/gen_rtcm.py` | added `msg1007`/`msg1008` frame generators |
| `docs/HANDOFF.md` | this entry; "Next steps" item 3 marked DONE |
| `docs/talk-outline.md` | Tier 1 hardware row now links to `tier1-hardware.md` |
| `docs/tier1-hardware.md` | new — finalised Tier 1 RF parts list |
| `docs/cfp-options.md` | new — CFP/venue comparison and review |

**Next steps, in priority order:**

1. **Pick a CFP** — ITM/PTTI's Oct 2 deadline is the nearest hard one on the
   table; Ekoparty is open now with no deadline surfaced yet; S4x27 (Aug 31)
   and Black Hat Singapore (opens Aug 26, closes Oct 16) are the other live
   windows. See `docs/cfp-options.md` for the full tradeoff.
2. Resolve the two open hardware questions in `docs/tier1-hardware.md`, buy
   the parts, bench-test the conducted path once they arrive.
3. **Rehearse the failed-start scenarios** — still the binding constraint on
   the demo per earlier sessions; untouched again this session.
4. Record the length-sweep demo clip (do not run it live).
5. Decide whether the misalignment defect gets filed as its own issue.

---

**Previous session:** 2026-07-27

## 2026-07-27, later: the demo has a screen

The visual build is done and verified against a live run — `demo_view.py`
collects and serves, `demo_view.html` draws. Two panes, because the demo spans
25:1 in scale and one frame cannot hold it: 50 m wide for the 30 m waypoint
leg, 6 m detail for the metre that actually matters. A persistent **RTK FIXED**
badge, and a mechanism panel on `M` that stays hidden through the cold open.
Neither pane ever moves or rescales — a frame that shifts mid-sentence is worse
than a small icon — so when truth leaves the detail frame during the transit it
gets an edge marker rather than a rescale. `Space` freezes the screen, which
§12 needs: the badge goes red on a stalled feed a second after the chain stops,
and the close depends on it still being green.

**Everything it reads is a passive tap, which is defensible rather than merely
convenient.** The GPS-claimed position and the fix flag come off :5903 as a
*second client* of RTKLIB's own NMEA server: `stream.c:178` gives `tcpsvr`
`MAXCLI=32` slots and `writetcpsvr()` fans every write out to all of them, so
the screen shows the exact bytes the flight controller is being fed and not a
re-derivation of them. Truth comes from a third MAVLink endpoint (SERIAL2,
:5763) — a separate socket, for the same reason SERIAL1 exists. Everything else
is read from logs the chain already writes.

Two things in RTKLIB's source shaped the design. `send_nb()` returns −1 on a
*short* write and `writetcpsvr()` answers that by dropping the client, so a
viewer that stops reading fast enough is disconnected without a word and the
map freezes while the aircraft keeps flying; the socket read is therefore its
own thread that does nothing but buffer, and it reconnects. And **HDOP must
never go on screen**: `outnmea_gga()` declares `double dop=1.0` and never
assigns to it, so an unchanging HDOP is a property of RTKLIB's writer rather
than evidence about the attack. Satellite count and correction age are real.

**The recorded fallback is free, and it is not a video.** Every live run writes
10 Hz state frames to `$T/view.jsonl`; `--replay` plays them back through the
same renderer. Identical pixels, rehearsable without booting SITL, and no
editing step to get wrong.

**A defect worth recording, because it produced exactly the display this
project exists to distrust.** The first collector run showed *phase 3, attack
armed* before the aircraft had booted. Each log is truncated only when its own
stage begins, so a viewer already running tails the *previous* run all the way
to its end — an attack-shaped screen with no attack present, which is the
fourth time something in this harness has managed that. `loop_demo.sh` now
truncates the viewer-visible logs before anything else starts, and the
collector clears the state derived from a file when it sees that file
truncated.

Three runs in total. One attacked run while building it, which is where the
base-position tap and the FIXED badge were first confirmed against live data.
Then, deliberately and in the right order, **a control run and an attacked
run**, with the screen read against `parse_sitl_log.py` on each — the table
below is that pair. (An earlier version of this section said the control had
not been run. True when written, and then it was; the table is the correction.)

| | control (`0`) | attacked (`211`) |
|---|---|---|
| gap on screen | 0.01–0.03 m | 1.38–1.42 m |
| base coordinate | `-3978243.8000`, moved 0.000 m | `-3978242.0000`, moved **1.800 m** |
| 1033 injected | 0 | 434 |
| badge | RTK FIXED throughout | RTK FIXED throughout, held 159 s |
| parser: waypoint miss | **0.04 m** | **1.37 m** |
| parser: displacement | — | 1.36 m opposite, residual 0.05 m |
| parser: vertical | — | 0.04 m against a 1.12 m lie |

The control reported *no sustained divergence* — which is the result that makes
the attacked run mean anything, and it is also what confirms both taps are
honest rather than decorative. These agree with the figures already recorded;
they are a reproduction, not a new measurement, so there is nothing here to
requote.

Harness changes are all additive. SERIAL2 and its stream rates are wiring, the
same category as everything else `loop.parm` sets, not tuning — worth knowing
because "why is that set?" is a question this demo has to survive.
`setvbuf(stdout, _IOLBF)` in `e2e_harness.c` and `python3 -u` on the flight
driver both exist because stdout to a file or a pipe is block-buffered at 4–8 KB
and the interesting lines are sparse: the base-position line prints *once* per
attack and would otherwise sit unflushed for minutes. Plus a status thread in
`inject_relay.py` for the live injection count, and one `hold:` print so the map
has a fixed reference marker — without one, two icons separating is unreadable,
because you cannot tell which of them moved.

**The control run found a defect in the screen, which is the point of running
it.** The relay tile read "RTCM frames forwarded **0**": with `LEN=0` there is
no splicer at all, so nothing counts frames while bytes flow perfectly. A zero
there, during the one beat whose whole claim is *"the chain is working and
nothing is happening"*, reads as a dead chain. The tile now shows bytes
relayed, which exists on both paths, and `inject_relay.py` runs its status
thread on the control path too. Deliberately *not* fixed by giving the control
run a splicer: that would make it frame-parse and reassemble the stream instead
of passing bytes through, which changes what the control measures.

**Three ways the chain can be down while the screen looks plausible** — all
found this session, all now either fixed or instrumented. A stale log tailed
from a previous run (fixed: truncate up front, reset on truncation). A wrong
`--scratch` path, where position and fix quality still arrive over TCP so the
screen looks alive while everything log-derived stays blank (now warns by
name). And the frame pump dying in its thread while the HTTP server keeps
serving, so the page loads, connects, and silently never updates (now
non-fatal). **Rehearsing a failed start is the outstanding item, and this is
what it is rehearsing for.**

**Also this session, and unrelated to the screen: the ARM offsets are done.**
`offsetof(sta_t,pos)` is 464 on all six ABIs checked, so `n1=211` is not an
x86-64 number. Full account under "Next steps" item 1, which is where completed
research items are recorded, and the authoritative version is in
`research/README.md` under "The payload length transfers unchanged".

## 2026-07-27: two claims tightened ahead of disclosure

Both were things already in writing that would not have survived contact with
the people best equipped to check them. Neither changes a result.

**"Nothing is logged" was imprecise, and the precise version is better.**
`decode_type1033` does trace, at level 3 — but it prints the *staging buffers*,
which the read loops cap at 31 characters. A message declaring `n1=255` logs a
line indistinguishable from a benign one, the attacker chooses those 31
characters, and the declared length never appears at any level. `update_antpos()`
— the function that adopts the corrupted coordinate — has no trace call at all;
the only trace of it is `svr->nmsg[index][4]++`. Written up as "What an operator
could see, with tracing fully enabled" in `research/README.md`, and corrected in
`README.md` and `eli5.md`. **The instrument exists and is pointed at the wrong
thing** is now the line, and it doubles as the one defence a vendor could ship
in an afternoon (§11).

**`refpos=POSOPT_RTCM` is not the default, and the honest framing is stronger
than the one it replaces.** `options.c:503` initialises `antpostype_` to 0
(LLH). But of the seven example configs in the tree, `rtkrcv/conf/rtk.conf` is
the only one configured for real-time RTK against an RTCM3 stream, and it is
the only one setting `ant2-postype=rtcm`. The rest are single-point or
post-processing, which have no correction stream to take a base position from.
So it is not "the normal RTK configuration" (vague, and challengeable) but
"every shipped config that does RTK at all" (checkable, and stronger). Table in
`research/README.md` under "Which configurations are exposed"; §11's operator
advice and the audience-question table updated.

## Disclosure timeline

Talk §11 turns on this, so it is recorded here as it happens rather than
reconstructed later.

| date | what | state |
|---|---|---|
| 2026-06-09 | FuzzingLabs (@raefko) file upstream issues #796–799; #799 is the type 1033 bug | all four still **open**, one comment each, no maintainer reply |
| 2020-12-29 | last commit to upstream's `rtklib_2.4.3` release branch | — |
| 2026-07-19 | this repo made public | — |
| 2026-07-27 | **repo made private** — a pause to think, not a retraction | reversible; see below |
| 2026-07-27 | **comment posted on #799**: the overflow reaches `sta.pos`, `antdes` cannot, the real-time path adopts it unguarded while `postpos.c:843` guards, Q=1 maintained, every measured build unfortified | awaiting response |
| 2026-07-27 | **Emlid notified by email** — their `reach` fork carries the defect and the inlined unguarded adoption; asked whether `_FORTIFY_SOURCE` is active in shipped firmware | awaiting response |

The #799 comment is deliberately self-sufficient: every claim in it is
checkable against RTKLIB's own source, so it stands as a dated priority marker
whether or not this repo is public. Held back from it: the four-rung magnitude
behaviour and the `n1=211` universal bound, the clamp (belongs in the PR), the
misalignment defect (belongs in its own issue), and Emlid entirely.

**Repo visibility.** Public 2026-07-19 to 2026-07-27, now private. Priority no
longer rests on the repo — it rests on the #799 comment, which is why that was
written to stand alone.

> **Corrected 2026-07-27.** An earlier version of this paragraph said the
> talk-outline commit had been "public for eight days, almost certainly never
> cloned", and treated the private window as a chance to rewrite it before
> anyone pulled it. That was wrong on the facts. `origin/master` was at
> `aa20a26` (2026-07-19) with **the local branch 27 commits ahead**: that
> commit was on no remote branch and had never been pushed, so it was never
> public and nothing could have cloned it. What *was* public for those eight
> days is everything up to `aa20a26` and nothing after.
>
> The reason to reword it is therefore not exposure but tone. The body claimed
> the methodology section was something the researchers who reported the bug
> could not match — a competitive comparison to the people this work credits in
> §11 and is currently in coordinated disclosure with. That reason stands on
> its own, and rewriting unpushed history costs nothing. **Paraphrased rather
> than quoted here, deliberately:** an earlier version of this note reproduced
> the sentence verbatim in order to explain why it was wrong, which put the
> remark back into the repository in the course of removing it. Describing it
> is enough. Deliberately not referring to either commit by hash either: the
> reword changes them, and stale hashes in this file have had to be repaired
> twice already.

**The patch is written and verified but deliberately not filed.** `check_clamp.sh`
measures it: benign streams byte-identical, all three attack variants left at
truth, UBSan finding gone with the control firing first. Holding the PR until
there is a response to the #799 comment — filing it immediately would spend the
one piece of leverage the comment has, and §11's slide reads better as "here is
the fix, filed, still unmerged" than as a PR nobody was asked for.

**Still to do:** the PR when the time comes, and a decision on whether the
misalignment defect gets filed as its own issue. A FuzzingLabs email is now
optional — commenting on #799 notifies @raefko automatically, since it is
their issue.

---

**Previous session:** 2026-07-26 (second session that day)

## Current state, in one paragraph

The closed loop works on a **stock ArduPilot parameter set** and now runs at
**`n1=211`** — the rung whose 2 m quantum bounds the error against *any* base
station, rather than `n1=212`, whose 512 m quantum happened to land on 2.4 m
against the old base. Control 0.03 m, attacked 1.39 m waypoint miss, 1.36 m
displacement opposite the offset. Two claims that were load-bearing earlier are
now **refuted by measurement and corrected in every document**: that
fortification is the distro default (Debian's own `rtklib`, on ARM, imports no
`*_chk` at all) and that the length byte is a fine-grained dial (four rungs,
each 256× the last). The defect is confirmed present in Emlid's `reach` fork,
so this is a product bug and not only a library bug. The vertical third of the
error is measured and is a **negative** — the baro outvotes it — which bounds
the attack and names the defence. The talk now has an outline
([talk-outline.md](talk-outline.md)), and the provenance claims are re-runnable
rather than asserted (`check_fork.sh`, `check_binary.sh`, `check_image.sh`).
Nothing is blocked.

**The research is no longer the bottleneck; the demo staging is.** Everything
claimed is measured, every document agrees, and the demo runs on a length that
generalises. What is missing is the visual build — map, two icons, a persistent
FIXED indicator — and a rehearsal.

> The visual build was done later the same day and verified against a live run
> — see "the demo has a screen" at the top of this file. **The rehearsal is
> still outstanding**, and on current state it is the binding constraint.

The one thing to carry forward: **run `./loop_demo.sh 0` before quoting any
closed-loop number.** Three harness defects have produced attack-shaped results
with no attack present, and the control run is what caught each of them. A
fourth — RTKLIB's frozen RMC course — degraded the attacked run instead, and
was caught only because the displacement disagreed with a figure measured a
different way. Both checks earn their keep.

## Since the last handoff

**The displacement sign is resolved, and it cost a number.** The two runs
never disagreed about physics. The closed-loop harness armed its injection on
a timer counted from RTKLIB's connect, which put it behind every startup delay
in the chain, and it lost the race: the GPS started lying at t=44.2 s while the
aircraft did not leave the ground until t=47.4 s. Phase 1 was never clean, and
the GUIDED hold target — read from the vehicle's own reported position once
airborne — was captured from a position the GPS was already falsifying. The
2.16 m "displacement while holding" was a takeoff transient anchored to that
lie. **It is withdrawn.**

Fixed by inverting the control: `ardupilot_demo.py --trigger-file` creates a
file once airborne and holding, and `inject_relay.py --trigger` waits for it.
No clock is involved, and the sequencing cannot race. Re-measured:

|  | control, 0 injected | attacked, 520 injected |
|---|---|---|
| GPS vs. truth after | 0.00 m | 1.91 m |
| displacement holding | — | 1.89 m, **opposite** the offset |
| waypoint miss | 0.09 m | 1.81 m |

Now agrees with the open-loop run component by component to within 7 cm — N,E
of the injected offset, the displacement and the miss — not just in magnitude.
So **"it repositioned to correct a drift that never happened" is now supported
by both runs**, which is the line the last handoff wanted and could not have.

> Those figures still carry `EK3_SRC1_VELXY 0`. They were superseded later the
> same session by a stock-parameter re-run — see the next section, and quote
> that table, not this one. The conclusion is unchanged; the numbers moved by
> a few centimetres.

`parse_sitl_log.py` gained two guards so this cannot recur silently: attack
onset now requires a *sustained* offset (a clean control run's 30 m transit
spikes 3 m of GPS lag and was being read as an attack), and it refuses to
report a displacement at all if the attack predates takeoff, naming the reason.
`sign_check.py` is new — truth, GPS and EKF in one frame, which is what made
the diagnosis obvious.

**Always run `./loop_demo.sh 0` first** — three harness defects have now
produced attack-shaped displacements with no attack present.

**Earlier that day:** the closed loop's instability was RTKLIB's NMEA reporting
0.00 knots regardless of motion, which ArduPilot's EKF3 fuses by default;
`EK3_SRC1_VELXY 0` worked around it and `prcopt.dynamics` did not, measured
against a known 1 m/s ramp. Loop latency measured 130 ms and was exonerated.
The shipped Windows binaries (`convbin.exe`, official and demo5 2.5.1) corrupt
the station coordinate silently, rc=0, magnitude dial reproducing to the last
digit, 32- and 64-bit identical; `_FORTIFY_SOURCE` is glibc-only and these are
Embarcadero builds where the abort has no equivalent to enable.

## The demo now runs on stock ArduPilot parameters

`EK3_SRC1_VELXY 0` is **gone**, and with it the last tuning deviation an
audience could ask about. The only parameters `loop_demo.sh` sets now are the
ones that wire the harness up: frame class, GPS type, serial protocol, stream
rates.

`NMEA_VEL=1` makes `e2e_harness.c` format the NMEA itself, filling
`sol.rr[3..5]` by differencing successive solutions at 5 Hz. GGA/GSA/GSV are
still RTKLIB's own writers and byte-identical; only RMC is ours, because of the
second defect below.

|  | control, 0 injected | attacked, 520 injected |
|---|---|---|
| GPS vs. truth after | 0.00 m | 1.92 m |
| displacement holding | — | 1.86 m, **opposite** the offset (residual 0.04 m) |
| waypoint miss | **0.04 m** | 1.86 m |

The control lands within **4 cm**, better than the 9 cm the workaround
achieved, and the attacked run still agrees with the open-loop measurement to
within 5 cm per component. Removing the deviation made the result *better*,
which is the strongest possible answer to "why is that setting changed?" — it
was compensating for RTKLIB's NMEA writer, never for the attack.

**Two defects had to be fixed to get there, and the second is the interesting
one.**

*Differencing alone was not enough.* `outnmea_rmc()` reports the previous
course whenever speed is below 1 m/s (`static double dirp` in `solution.c`,
starting at 0.0), so a correct speed arrives with a frozen bearing. Measured
with no vehicle in the loop: fed 0.5 m/s due east, RTKLIB's RMC says 0.499 m/s
on a course of 0.0° — 90° wrong. ArduPilot rebuilds velocity as speed × course
and a hovering multirotor lives entirely in that band, so it is a *consistent*
error the estimator integrates rather than noise it averages away. The aircraft
oscillated ±3 m while holding, while the waypoint leg — flown above 1 m/s where
the course is live — looked perfect. `own_rmc()` computes the course at every
speed. Verified: 90.0° at 0.5 m/s east, 225.1° at 0.3 m/s south-west.

*A stale binary.* The first `own_rmc()` attempt failed to compile (`NMEA_TID`
and `KNOT2M` live in `solution.c`, not `rtklib.h`) and both scripts silently
ran the *previous* binary, because the build check tested `[ -x $T/e2e_loop ]`
— which passes when the old file is still there. It cost a full flight and
nearly the wrong conclusion. Both scripts now `rm -f` first and test gcc's exit
status.

## Startup reliability — three guards added

A live demo has to fail loudly and be immediately retryable. None of these
were true this morning.

- **`require_port` after every stage.** A leftover process held :5901, so
  `gnss_sim` never bound, the chain ran empty, and it surfaced four minutes
  later as `EKF never became ready` (flags 0x0400). On stage that looks exactly
  like the attack failing. Now it aborts in 10 s naming the port and the log.
- **`-DSVR_REUSEADDR`.** RTKLIB only sets `SO_REUSEADDR` on a TCP server under
  this flag, so every run left :5901/:5902/:5903 unbindable for the TIME_WAIT
  window and the *next* run died at startup. A demo you cannot immediately
  retry is not a demo.
- **Build failures are fatal**, as above.

Two environment traps re-confirmed the hard way: `pkill -f loop_demo.sh` kills
the invoking `bash -lc` too (it matches its own command line), and a
`tail`-piped run shows no output at all until it exits — watch
`/tmp/rtk-loop/flight.log` directly instead.

## Where this is going

**Undecided as of 2026-07-31, and nothing is time-critical.** There is no
deadline, no submitted CFP, and no publication date. Two possible outputs exist
and neither is committed to:

- **A conference talk with a live demo.** Planned 2026-07-26, still viable, no
  venue. The outline and its checklist are in
  [talk-outline.md](talk-outline.md); treat that document as *contingent*, not
  as a plan of record.
- **A long-form article for a general audience**, drafted at
  [blog-1033-draft.md](blog-1033-draft.md). Complete and readable, **not
  published**, with its three publication blockers listed in an HTML comment at
  the top of the file. It stands alone and does not depend on the talk
  happening.

**What that means for anyone picking this up.** The research is at a natural
resting point: both attacks are measured, both are written up, and the
authoritative record is [research/README.md](../research/README.md). Nothing
below is urgent. Do not treat the talk checklist as a live constraint unless a
talk is actually being pursued again — the live-demo requirement is what made
harness realism and startup reliability load-bearing, and if there is no talk,
those items drop in priority.

**What still matters regardless of the output:** the accuracy discipline. Every
claim in this repo is either measured or explicitly labelled as reasoned, and
the standing caveats below say which is which. That is what makes the work
usable for either path — or for neither.

## Next steps, in the order I would take them

Effort figures are rough and assume the environment is already set up (see Key
Parameters). **None of these is blocking anything**; they are what a next
session would pick up if the work continues.

> **These are the *research* items.** Talk-preparation tasks — demo visuals,
> the recorded fallback, rehearsing a failed start, hardware to order — live in
> [talk-outline.md](talk-outline.md#pre-submission-checklist). Those are only
> relevant if a talk is being pursued; see "Where this is going".

**1. ARM offsets — DONE 2026-07-27.** `offsetof(sta_t,pos)` is **464 on every
architecture checked**: x86-64, armhf, armel, arm64, riscv64, ppc64. Identical
layout throughout, so the payload lengths measured here are not x86-64 numbers
and `n1=211` needs no adjustment for an ARM target.

`check_offsets.py` measures it, and nothing runs on the target: the compiler
knows the offset at translation time, so each candidate is put to it as a
`_Static_assert` and the answer read off compile success. Cross-compiler is
`zig cc` — clang, installable with `pip install --user ziglang`, which
`arm-linux-gnueabihf-gcc` was not without root. Control is the system gcc
reading the same offsets on x86-64; it reproduces the 464 already in this repo,
and the script refuses to report anything if the two disagree.

The result worth keeping is the **armel** row: soft-float, no FPU in the ABI,
and still 8-byte `double` alignment, because that is AAPCS rather than a
property of the hardware. The obvious way this could have differed does not
occur on anything Debian ships RTKLIB for. Written up in `research/README.md`
under "The payload length transfers unchanged".

**2. The fortified column, end to end — DONE 2026-07-31.** Both columns are now
flown, same aircraft, same profile, same `n1=211`, differing only in the build.

    FORTIFY=1 HOLD=1 ./loop_demo.sh 211      # abort column
    HOLD=1 ./loop_demo.sh 211                # silent column (control)

| | fortified | unfortified |
|---|---|---|
| GPS `Status` | 6 → **0** at 87.5 s | **6 throughout**, 49.2 → 188.2 s |
| `ERR` records | 4 | **0** |
| failsafe | EKF variance → auto **LAND**, 4.0 s after GPS loss | none |
| on the ground | 120.6 s, 0.50 m/s, disarmed 122.7 s | flew the leg, reported arrival **1.42 m off** |

Written up in `research/README.md` under "What the abort does to the aircraft",
and the reasoned-not-measured labels are out of all four documents. The
`SmartRTL deactivated: bad position` line is worth keeping in the pitch — the
aircraft *could not* RTL, so fail-stop means landing wherever it happens to be.

**Two things this produced that were not the point.**

*A harness trap, and it nearly became the answer.* Pointing SITL's GPS port
straight at RTKLIB means the abort **closes the socket**, SITL fails the port
(`connect failed on port 5903 ... Bad file descriptor`), and the simulator
exits — flight log ends at 88.1 s, failsafe logic never runs. That is the
simulator quitting, not the aircraft responding, and it looks enough like a
result to write up as one. `nmea_hold.py` (new) holds the client socket open and
goes silent when the producer dies, which is what a crashed receiver looks like
from the far end of a UART. `HOLD=1` inserts it; the unfortified control run
through the same proxy reproduces 1.42 m against the 1.40 m recorded 2026-07-27,
which is what makes the proxy transparent rather than assumed to be.

*`FORTIFY=1` and `HOLD=1` are both default-off* precisely so the stage demo is
untouched. Do not change the defaults.

**And then the finding that changed the framing.** The first write-up of this
reported the abort as the *safe* column. That was wrong, and the correction is
now §5b of the talk. `SmartRTL deactivated: bad position` means the aircraft
**cannot return home** — landing where it stands is its only option, and the
attacker chooses when that happens. So the abort is a **denial-of-flight
primitive with attacker-controlled timing**, which the unfortified build does
not offer.

`land_drift.py` (new) measures the targeting error: **10.13 m** of horizontal
drift between GPS loss and touchdown, from a 15 m hover, 29.1 s descent,
monotonic. Enough for a lake or a field; not enough for a lane of traffic. It
refuses a log with no failsafe in it, so it cannot report a forced landing that
did not happen.

**The framing that survives:** two attacks, not a bug and a mitigation.
Unfortified is precise/silent/small; fortified is crude/loud/total. *Do not
report fortification as a fix anywhere* — the fix is the clamp. Written up in
`research/README.md` under "The abort is a second attack".

**Still not measured:**
- The crash loop on restart. The injector splices a 1033 after every 1005, so a
  restarted process should die immediately on the next one; two-minute check,
  forecloses "just restart it". The run above ends with the aircraft on the
  ground instead.
- **Dispersion as a distribution.** 10.13 m is one sample in zero wind. Repeats
  across altitude and `SIM_WIND_SPD` would turn it into a claim worth quoting;
  right now it is a floor. If §5b gets challenged, this is the gap.

**3. `decode_type1007` / `1008` — DONE 2026-08-09.** Same harness, different
message type. The negative result held exactly as expected: both share the
same unclamped-`strncpy`/zero-padding shape as 1033, but `antdes` (offset 128)
and `antsno` (offset 192) sit too early in `sta_t` to reach `pos` at 464, or
to leave the struct at all, even at the maximum legal declared length (255).
Memory-safety only, no positioning impact, on either type — confirmed by
measurement (`check_1007_1008.py`), not just offset arithmetic. Answers "why
1033?": of the five descriptor fields across all three types, only
`rectype`/`recver`/`recsno` sit after `pos`, and all three belong to 1033.
Written up in `research/README.md` under "`decode_type1007`/`1008`: same
shape, measured to not reach `pos`".

**4. A patch PR to RTKLIB — nearly free.** The fix is a **five-line** clamp (one
per declared length; `research/README.md`, "The fix"). It will probably sit
unmerged, which is the point: "here is the five-line fix, filed, still unmerged"
closes better than "still unpatched".

**5. Real hardware — a few hundred dollars, a weekend, biggest credibility
gain.** Note the F9P cannot be the target: it does not run RTKLIB. The setup is
an F9P feeding real observations to **RTKNAVI on Windows** — now measured as
unfortified — with the 1033 injected into an NTRIP correction stream. Upgrades
the result from simulated to real satellites, real receiver, shipped software.

**6. Embedded firmware (Emlid Reach) — SOURCE DONE 2026-07-26, binary blocked.**
`emlid/RTKLIB` branch `reach` carries the defect unchanged, the same `sta_t`
layout (so the same payload lengths work), and the unvalidated adoption inlined
into `updatesvr()` at `rtksvr.c:219`. Written up in `research/README.md`. That
converts "a bug in a hobby library" into "a bug in a product you can buy", and
ArduPilot documents Reach feeding a flight controller over ERB with corrections
arriving on the telemetry radio — the harness chain with a real product in it.

*The Navio image was pulled and is a dead end for RTKLIB, but paid off anyway.*
`emlid-raspbian-20220608.img` (718 MB, sha256 `d16b66d5…`) ships **no RTKLIB**:
in the whole 3.7 GB rootfs the only `str2str` hits are OpenLDAP symbols matching
as a substring, and the only `RTKLIB` hit is an APT metadata stanza. Read
rootless with `debugfs` on a `dd`-carved partition — no `sudo`, which the
project settings deny.

That APT stanza is what paid off: **Debian packages RTKLIB 2.4.3.b34**, the
exact version measured here, for 12 architectures. The armhf console apps were
fetched and checked, and they **refute the prediction that Linux targets abort**
— no `*_chk` imports at all, plain `strncpy`/`sprintf` present, decoder
statically inside `rtkrcv`. Written up as "The distro package is unfortified
too" in `research/README.md`. Every build actually measured now — two Windows
distributions and one Linux/ARM distro package — is in the silent column.

*Still open: the Reach firmware binary itself.* `files.emlid.com` 403s all
image paths and the Flash Tool fetches at runtime. Two ways left: observe what
URL the Flash Tool requests (free, uncertain), or buy a Reach M2 (~$300,
certain). Note the prediction that it would abort no longer has a basis.

**RF delivery: now planned, and conducted only.** Superseded 2026-07-26 — the
talk wants it. The constraint that produced the original "not doing" stands
unchanged and is the design, not a caveat: 433/868/915 MHz is where real survey
and agricultural rigs operate, so **everything goes down coax through
attenuators into a shielded enclosure, never a radiated signal**. "No RF was
transmitted into open air" remains a virtue of this work and is also the only
version that is reliable on a conference floor.

The Emlid finding changed the priority. Reach uses **LoRa** for its base↔rover
correction link (902–928 MHz US, 863–870 MHz EU), which is SX1262 — the same
chip as the Heltec V3 boards already on hand. Professional rigs (Trimble
TDL450, Satel 4Pro) are a different animal: GMSK/4FSK, 403–473 MHz, transparent
serial. Full plan, both paths, and the hardware list in
[talk-outline.md](talk-outline.md#8-delivering-it-over-the-air).

## Commits, most recent session first

**2026-07-27, later session.** Seven commits, `fe9aab3..238fa57`, and the first
push since 2026-07-19 — `origin/master` had been 27 commits behind and is now
current.

| commit | what |
|---|---|
| `fe9aab3` | the demo visualisation (`demo_view.py`, `demo_view.html`) and the passive taps that feed it: SERIAL2 for truth, line-buffered harness stdout so the base-position line lands when written, a relay status thread, and a printed hold point |
| `441ead9` | **corrected** the claim that the talk-outline commit had been public for eight days — it was never pushed. The reword still happened, for tone rather than exposure |
| `c20ba39` | repaired the commit hashes the reword moved, same as `b1f69a2` before it |
| `846ff4a` | stopped reproducing the reworded remark in the course of explaining it — the correction had reintroduced the thing it was correcting |
| `54415a8` | replaced this section's "files changed, UNCOMMITTED" predecessor with a commit table, once there were commits to record |
| `2d98bd4` | committed the stage fallback recording, cropped at both ends only — it had lived solely on the WSL virtual disk, which is the worst possible home for the artifact whose job is to survive things going wrong |
| `238fa57` | **`offsetof(sta_t,pos)` measured across six ABIs — 464 on all of them**, so the payload lengths are not x86-64 numbers. Closes the last open item in "which builds are affected" |

Files in `fe9aab3`: `research/demo_view.py` and `research/demo_view.html` new;
`loop_demo.sh` (SERIAL2 + stream rates, truncate the viewer-visible logs up
front, `python3 -u` on the flight driver), `e2e_harness.c` (`setvbuf` line
buffering), `inject_relay.py` (status thread on both the injecting and the
passthrough path, reporting bytes), `ardupilot_demo.py` (print `hold:`), plus
`.claude/settings.json` now tracked and its machine-local sibling ignored.

**2026-07-26, later session.** Eight commits, `3cd70d4..21dc20c`:

| commit | what |
|---|---|
| `3cd70d4` | measured the rungs 209–214 — the dial has four, `n1=211` is the one that generalises; resynced the ELI5, which still carried withdrawn numbers and a workaround that no longer existed |
| `4f27f64` | Emlid `reach` fork confirmed to carry the defect, the layout and the unguarded adoption — a product bug, not only a library bug |
| `81c0c73` | **refuted** the prediction that Linux targets abort: Debian ships RTKLIB 2.4.3 b34 for 12 architectures and the armhf build is unfortified |
| `5f82c3e` | moved the demo to `n1=211` at a base sited to make it visible; control 0.03 m, attacked 1.39 m |
| `5ad69c4` | doc consistency pass — two claims this session falsified were corrected in every document, not just where they originated |
| `181f6e7` | measured the vertical: a 1.12 m height lie moved the aircraft 0.04 m, because the baro outvotes it. The axis with a redundant sensor resisted |
| `5ddfcdf` | the talk outline, the conducted-RF delivery plan, and the hardware list |
| `21dc20c` | surfaced the provenance tooling — `check_fork.sh`, `check_binary.sh`, `check_image.sh`, `pick_base.py` — so the Emlid/Debian/Navio claims are re-runnable rather than asserted |

**2026-07-26, earlier session.** *(These two were originally recorded here as
`e973bdd` and `5b9a0f5`, which are not in the repo — the branch was rebased
after the note was written. The real hashes are below; the file lists are
unchanged.)*

Committed in `fb8a3f7` (the sign resolution):

| file | change |
|---|---|
| `research/inject_relay.py` | `--trigger PATH`: wait for a file instead of counting seconds |
| `research/ardupilot_demo.py` | `--trigger-file PATH`: create it at phase 2, once airborne and holding |
| `research/loop_demo.sh` | uses the trigger; `DELAY` gone |
| `research/parse_sitl_log.py` | sustained-offset onset; refuses a displacement if the attack predates takeoff; phase 3 no longer keyed off the attack time |
| `research/sign_check.py` | new — truth, GPS and EKF position in one frame |
| `research/README.md`, `docs/HANDOFF.md` | corrected numbers, third harness defect written up |

Committed in `034d8a7` (the stock-parameter demo):

| file | change |
|---|---|
| `research/e2e_harness.c` | `derive_vel()` + `own_rmc()` + `NMEA_VEL=1` own-NMEA path; `DYNAMICS` comment corrected to say it does not work |
| `research/loop_demo.sh` | `NMEA_VEL=1` replaces `DYNAMICS=1`; `EK3_SRC1_VELXY 0` removed from `loop.parm`; `require_port` after each stage; fatal build failures; `-DSVR_REUSEADDR` |
| `research/loop_latency.py` | `feed --ramp/--ramp-dir`, new `speed` subcommand checking speed *and* course |
| `research/loop_latency.sh` | `MODE=speed`; same build fixes |
| `research/README.md`, `docs/HANDOFF.md` | stock-parameter numbers, the `dirp` course defect written up |

## Key Parameters/Settings

| | |
|---|---|
| branch | `master` |
| RTKLIB | `~/RTKLIB` in WSL, branch `rtklib_2.4.3`, commit `180043e` |
| ArduPilot SITL | `~/apsitl/arducopter` (prebuilt ArduCopter 4.7.0) |
| run command | `RTKLIB=/home/tim/RTKLIB BIN=/home/tim/apsitl/arducopter bash ./loop_demo.sh` from `/mnt/c/Users/tim/work/rtk/research` in WSL Ubuntu — `LEN` now defaults to 211 |
| control run | the same with `0` — injection disabled. Run it *first*; it should land within centimetres (last: 0.03 m) |
| demo screen | `python3 demo_view.py` from `research/` in WSL, **started before the run**; open `http://localhost:8080/` in a browser on the Windows side (WSL localhost forwarding is verified working). Keys: `Space` freeze, `M` mechanism panel, `T` trails, `F` fullscreen, `R` reset trails |
| screen, for §12 | `Space` freezes the last frame and stops accepting new ones. Hit it *before* the run ends: a second after the chain stops the badge correctly goes red on a stalled feed, and the close needs the indicator still green |
| screen, gotcha | the "held for N s" counter starts when the *page* connects, not when the fix did, so a late page load understates it. Open the page first |
| recorded fallback | `python3 demo_view.py --replay /tmp/rtk-loop/view.jsonl` — every live run records one automatically. Same renderer, so it is the demo played back rather than a video |
| **fallback, before travelling** | `view.jsonl` is **truncated at the start of every run**, so the fallback is destroyed by the first live attempt at the venue. Copy a known-good one somewhere durable and point `--replay` at *that*: `cp /tmp/rtk-loop/view.jsonl ~/stage-fallback.jsonl`. Verified good one recorded 2026-07-27 (4142 frames, control 0.0x m, attacked 1.40 m, base delta 1.800 m) |
| leaving it up | the viewer survives between runs: it detects each log being truncated and clears the state derived from it. Start it once, re-run `loop_demo.sh` as often as needed |
| latency probe | `RTKLIB=/home/tim/RTKLIB bash ./loop_latency.sh 90` — no vehicle, prints the loop delay |
| `LEN` | **211** — the rung that generalises: a 2 m quantum, so bounded error against any base. 212 was a 512 m quantum that happened to land on 2.4 m against the old base |
| vertical | measured, and it is a **negative**: a 1.12 m height lie moved the aircraft 0.04 m, because EKF3 takes height from the baro (`EK3_SRC1_POSZ`). Control step 0.000 m. The attack is horizontal-only on this airframe |
| attack trigger | `$T/attack.go`, created by the flight driver at phase 2. Replaced the `DELAY` timer, which raced the takeoff |
| speed check | `MODE=speed RTKLIB=/home/tim/RTKLIB bash ./loop_latency.sh 45` — no vehicle; feeds a 1 m/s ramp, prints the ground speed the RMC reports |
| `NMEA_VEL` | `1` in `loop_demo.sh` — harness formats the NMEA and derives the velocity. Unset reverts to RTKLIB's writer and the documented file/serial runs |
| `RUN` | 260 s — must outlast the whole flight profile or SITL loses its GPS mid-flight |
| ports | 5901 base, 5902 rover, 5911 relay, 5903 NMEA, 5760 SITL SERIAL0, 5762 SERIAL1 |
| base ECEF | `-3978243.8000,3382841.1715,3649902.7667` — sited 1.80 m above the 2 m lattice point so `n1=211` is visible. Not `-3978243.9998`: 0.2 mm from the boundary would collapse to ~0 under any sub-mm shift. The old `-3978242.4348` gives 0.43 m at 211 |
| scratch | `/tmp/rtk-loop` (logs: `sim.log`, `relay.log`, `rtklib.log`, `mavpos.log`, `sitl.log`, `flight.log`) |

Environment traps worth remembering:

- `pkill -f <pattern>` matches the invoking `bash -lc '...'` command line
  itself if the pattern appears in it, so an ad-hoc cleanup command can kill its
  own shell and exit silently. Hit again this session.
- `$VAR` does not survive `wsl.exe -- bash -lc '...'` from Git Bash. Use
  explicit paths or a script file, and `MSYS_NO_PATHCONV=1` for `/mnt/...`
  arguments.
- **WSL tears the VM down when the last session closes, killing anything
  started in it.** This is what makes "start the viewer in one window, the run
  in another" fail: the viewer dies seconds later and the browser reports
  connection refused, which looks like a network or IPv6 problem and is not.
  It also silently killed a `loop_demo.sh` run mid-flight earlier the same day.
  **Start the collector and the run from the same shell** — `demo_view.py ... &`
  followed by `loop_demo.sh` — or from one script. Once a collector genuinely
  is up, both `localhost:8080` and `127.0.0.1:8080` are reachable from the
  Windows side; that crossing was never the problem.
- `nohup ... &` inside a one-shot `wsl.exe -- bash -lc` does not reliably
  survive either, for the same reason. Run the thing in the foreground of a
  session that stays open.

## Standing caveats

- The harness derives its own GPS velocity by differencing, standing in for
  Doppler. Estimator parameters are stock now, but the *receiver* is doing
  something a real one would not have to.
- **No receiver firmware binary examined.** Emlid Reach's *source* is confirmed
  affected (`./check_fork.sh emlid/RTKLIB reach`), but the shipped firmware was
  not obtainable. Say "the source is affected", not "the product behaves this
  way".
- **ARM: no longer a caveat.** Resolved 2026-07-27 — `offsetof(sta_t,pos)` is
  464 on x86-64, armhf, armel, arm64, riscv64 and ppc64 alike, so the payload
  lengths transfer unchanged (`check_offsets.py`). What remains is narrower and
  worth stating precisely: this measures the **ABI**, via two compilers that
  agree, not the specific binary Debian shipped. A build using a non-default
  packing or a patched header would not be covered, and none was checked.
- Windows measurement covers the decode and coordinate corruption, not the
  real-time adoption — the GUI apps were not driven.
- The vertical result is specific to a multirotor with a barometer. A vehicle
  that fuses GPS height should be expected to move in all three axes; untested.
- The demo base is *sited* so the `n1=211` rung is visible (1.80 m of a 2 m
  quantum). At an arbitrary base the error is a uniform draw in [0, 2) m. The
  bound is the claim, not the 1.8.
- **Deployed configurations are unmeasured.** The config survey covers the
  example files in the source tree only. What RTKNAVI's GUI selects on a fresh
  install, what demo5 ships, and what Emlid Reach's web UI configures are all
  unchecked — and they are what a claim about real receivers would rest on.
- **The abort column is one aircraft, one profile.** Measured 2026-07-31 on
  ArduCopter 4.7.0 / EKF3 / stock failsafe params. The *direction* — a
  detectable event versus none — is the claim; 4.0 s and 33.1 s are
  illustrative. Fixed-wing, ground vehicles and non-default `FS_EKF_ACTION` are
  untested, and the crash-loop-on-restart behaviour is still reasoned only.
- **Any run where RTKLIB is expected to die needs `HOLD=1`.** Without the proxy
  the socket closes, SITL quits on the port, and the run measures the simulator
  rather than the aircraft. See next step 2.
- **Never describe `_FORTIFY_SOURCE` as the fix.** It exchanges a silent
  position-corruption attack for a loud forced-landing attack that the
  unfortified build cannot perform. Both columns are attacks; the fix is the
  five-line clamp. This corrects the framing used before 2026-07-31.
- **The 10.13 m landing dispersion is a floor, not a bound.** One run, zero
  wind, 15 m hover, near-stationary aircraft. Do not write "±10 m".

---

Everything below is from the 2026-07-25 session and is retained for the
reasoning, not as current state.

The authoritative record of the research itself is
[research/README.md](../research/README.md). This file is only the working
state: what moved this session, what is broken, and what to do next.

## What Was Done

Closed the last gap in the writeup's Limitations section — a single
packet-to-propeller chain, with the offset reaching the aircraft *only* as a
malicious RTCM3 1033 in the correction stream. It now runs end to end.

- **Restored the RTKLIB checkout.** It was missing from WSL, so nothing built.
  Cloned at the pinned commit `180043e` (2.4.3 b34) to `~/RTKLIB`.
- **Broke the startup deadlock in `gnss_sim` live mode.** It emitted one epoch
  per stdin line, so no observables existed until the vehicle fed a position —
  but the vehicle needed a fix to exist. Live mode now free-runs at `rate` Hz
  off its own clock, with a reader thread updating the rover position, starting
  from the base coordinate. Verified standalone: 150 epochs served and 106
  solutions with zero positions fed.
- **Fixed a vertical feedback runaway.** `mav_pos.py` fed `GLOBAL_POSITION_INT`
  altitude — the vehicle's own *estimate* — back in as truth, so the estimate
  defined the observables that then confirmed it. Solution height ran 75.8 m to
  −143 m in 40 s and the aircraft never got airborne. Truth altitude now comes
  from `SIM_STATE`; if it never arrives the height is held constant rather than
  falling back to the estimate.
- **Split the MAVLink endpoints.** The position feed and the flight driver both
  connected to SERIAL0, which takes one client at a time, so the second got EOF
  — indistinguishable from a vehicle that will not arm. Feed is on SERIAL1.
- **Stopped the flight driver double-counting the attack.** `ardupilot_demo.py`
  applied its own `SIM_GPS1_GLTCH_*` offset; added `--no-glitch` for the loop.
  Its waypoint was also hardcoded to the RINEX site, 3.4 km from where the loop
  flies — now anchored to the actual hold position and passed to the parser.
- **Fixed `inject_relay.py` stats** reporting `0 frames, 0 injected` while
  working (counts were kept on a second, unused splicer).
- **Removed two junk binaries** (`research/:5901`, `research/:5902`) committed
  by accident in `c49bfe2`, and made batch mode reject a port as an output path.

## Current State

The chain runs: SITL truth -> `gnss_sim` -> on-path relay -> RTKLIB -> NMEA ->
SITL's GPS. The attack propagates at **Q=1 (RTK fixed)**:

```
clean    35.132066148  139.624302129  75.7912   base -3978242.4348
attack   35.132075630  139.624284796  74.3630   base -3978240.0000
         N +1.05  E -1.58  U -1.43  ->  2.4 m,  Q=1 in both
```

691 injections, base position adopted from the stream, no file editing
anywhere. The aircraft armed, flew all three phases and landed.

*(All of this is committed now — `ea6f5f2` onward, merged to `master`.)*

## What's Blocked

**The vehicle destabilises, and the cause is the harness, not the attack.**
The GPS-vs-truth offset stays pinned at ~2 m for the whole flight — the attack
does exactly what the writeup documents. The aircraft's *true* position is what
diverges:

```
t=45..57   within +-0.5 m, offset 1.90 m     <- stable, attack already present
t=59  +-1 m    t=71  +-3 m    t=83  +-7 m
t=87  -26 m    t=91  -68 m    t=95  -103 m   t=101  -113 m
```

Growing oscillation, period ~9 s, amplitude roughly doubling per cycle. That is
a delayed-feedback instability: the loop latency (mav_pos -> FIFO -> epoch ->
RTCM -> relay -> RTKLIB solve -> NMEA -> SITL) is far longer than the ~200 ms
GPS delay ArduPilot's EKF assumes.

> **That last sentence was wrong — REFUTED 2026-07-26.** The loop delay
> measures 130 ms, faster than a real GPS. The actual cause was RTKLIB's NMEA
> reporting zero velocity to an EKF that fuses it. The observation of the
> oscillation was sound; the explanation was not.

**Do not quote the 39 m drift or the 157 m waypoint miss from this run.** They
are the instability, not attack effects, and nothing from the closed loop
should go into `research/README.md` until the vehicle is stable.

*(Superseded — all four are done. The current plan is "Next steps, in the order
I would take them" near the top. Item 1 there is what came out of item 1 here
going the way it did.)*

## Files Changed

| file | change |
|---|---|
| `research/gnss_sim.c` | self-paced live loop + position reader thread; batch mode rejects a port as an output path |
| `research/mav_pos.py` | truth altitude from `SIM_STATE` (requested by message id); no estimate fallback |
| `research/ardupilot_demo.py` | `--no-glitch`; waypoint anchored to the hold position and printed for the parser |
| `research/loop_demo.sh` | untracked — split MAVLink endpoints, `RUN` 170 to 260, passes `--target` to the parser |
| `research/inject_relay.py` | untracked — on-path relay; stats now kept on the splicer doing the work |
| `research/:5901`, `research/:5902` | deleted (staged) |

## Network Interpretation — RETRACTED

Kept because the conclusion was published in an earlier version of this file.

An earlier version claimed that `rtklibexplorer/RTKLIB` is the dominant hub of
the fork network, with upstream "clearly secondary." **That conclusion is
withdrawn — it was an artifact of an incomplete crawl, not a property of the
ecosystem.**

Two defects produced it:

1. **Truncated crawl.** `get_forks()` in `rtklib_fork_network.py` assigns
   `CACHE[repo_id] = batch` inside the pagination loop, so each page overwrites
   the previous one, and a cache *hit* short-circuits the crawl entirely. The
   resulting graph covers ~6% of upstream's ~1,800 forks (and the oldest ones,
   since the API call sorts by `oldest`) against ~100% of rtklibexplorer's 367.
   The hub was manufactured by the sampling.
2. **Centrality is meaningless on this graph.** GitHub fork graphs are trees —
   every fork has exactly one parent. Betweenness centrality on a tree is a
   monotone function of subtree size, so it cannot surface a chokepoint that
   simple descendant-counting would miss.

Separately, fork count measures curiosity, not deployment: a fork is one click,
and most are never touched again.

The fork-mapping line of work has been **dropped**. `rtklib_fork_network.py`,
`rtklib_fork_cache.json`, `rtklib_fork_graph.graphml`, and
`rtklib_seed_nodes.csv` are retained only as a record of the attempt. Do not
cite any figure from them.
