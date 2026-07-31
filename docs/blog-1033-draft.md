---
title: "The GPS That Was Certain, and Wrong"
date: 2026-07-31
category: tech
tags: [gnss, rtk, rtklib, drones, vulnerability-research]
summary: >
  A single fake antenna name can move a survey rover two metres while it insists
  it has a perfect fix — or, on a differently-compiled copy of the same program,
  bring a drone down wherever the attacker likes. A long walk through how, for
  people who have never touched GPS software.
---

<!--
DRAFT - NOT PUBLISHED. Status as of 2026-07-31.

No publication date. A talk may or may not happen; this article does not depend
on that decision and is written to stand alone.

MUST FIX BEFORE PUBLISHING - do not skip these, they are not polish:

1. FUZZINGLABS ATTRIBUTION. They found and reported the overflow (2026-06-09,
   RTKLIB issues #796-799) and described it accurately. This article mentions
   them once. Add an explicit "what is theirs / what is new here" passage right
   after the bug is introduced, or the piece reads as though it is claiming
   their find. See research/README.md, "Relationship to the FuzzingLabs
   disclosure", which already does this properly.

2. TIME-RELATIVE PHRASES ROT. Part 14 says "no reply in seven weeks" and Part 13
   says "a few days ago". Both were true on 2026-07-31 and will be wrong later.
   Re-anchor to absolute dates and add a visible "status as of <date>" line so a
   stale post is obviously stale rather than quietly wrong.

3. THE UNNAMED FORK. Part 14 says "at least one commercial GPS manufacturer's
   public fork". It is emlid/RTKLIB, branch `reach`, a public repository -
   naming it is a statement of fact. The thing to protect is the PRODUCT claim
   (no firmware binary has been examined), not the repository name. Decide, and
   either name it or cut the paragraph; as written it reads as insinuation.

IF THE TALK HAPPENS FIRST: drop the "I am not publishing the lookup table" note
in Part 6 - holding back from readers what a room was shown reads badly - and
link the slides or video at the top.

IF THERE IS NO TALK: consider adding the second defect (the misalignment bug,
which is not in FuzzingLabs' report), strengthening the product-relevance
argument, and releasing the length-to-magnitude table, since holding it back
then serves nothing.

Numbers in this article are checked against research/README.md as of 2026-07-31.
The mantissa table in Part 6 was generated, not reasoned about, and reproduces
three independently measured values: the 5 mm case, the 1.800 m stage-demo
delta, and the 2.4348 m result.
-->

There is a bug in a piece of free software called RTKLIB that I have been
picking at for a few weeks. On the surface it is a boring bug — the kind that
gets filed, ignored, and forgotten. Underneath it is something more interesting:
a way to make a very expensive, very precise GPS receiver report a location that
is wrong by a couple of metres, while it continues to insist that its answer is
perfect.

No crash. No warning. Nothing in any log.

I flew a simulated drone into it and the aircraft did exactly what it was told,
arrived where it believed it had been sent, and shut down normally — while
sitting well over a metre from where it thought it was. Then I rebuilt the same
software with one different compiler setting and flew it again, and this time
the aircraft fell out of the sky on cue.

This post is the long version, written for people who have never thought about
GPS software in their lives. If you already know what a mantissa is, you can
skim; I am going to explain everything.

---

## Part 1: How GPS knows where you are, and why it isn't good enough

A GPS satellite does one useful thing: it shouts the time, constantly, very
accurately.

Your receiver listens to several of these shouts at once. Because it knows how
fast radio travels, and it knows roughly what time it is, it can work out how
long each signal took to arrive. Multiply by the speed of light and you have a
distance to each satellite. Get four or more distances and there is only one
point in space where you could possibly be standing.

That is the whole idea, and it works remarkably well for something that involves
listening to clocks in orbit. It will put you within a few metres.

A few metres is fine for finding a restaurant. It is useless for a great many
other things. It is useless for surveying a property boundary. It is useless for
a tractor that has to plant this year's rows between last year's rows. It is
useless for a drone inspecting a bridge, or landing on a platform, or flying a
mapping grid where the photos have to line up.

Why only a few metres? Because the signal has to cross the atmosphere to reach
you, and the atmosphere is not a vacuum, and it is not consistent. The
ionosphere slows the signal down a bit. The troposphere slows it down a bit
differently. The satellite's own clock and orbit are known slightly imperfectly.
Each of these adds a small error to every distance, and the small errors add up
to a few metres of uncertainty.

Here is the important part: **those errors are almost identical for two
receivers standing near each other.** The same patch of atmosphere is sitting
over both of you. The same satellite clock is slightly wrong for both of you.

That shared error is the opening.

## Part 2: RTK, and the trick that gets you centimetres

If two receivers a few kilometres apart are both being lied to in the same way,
and one of them *already knows exactly where it is*, then it can work out how
big the lie is right now and tell the other one.

That is Real-Time Kinematic positioning — RTK. It has two halves:

- A **base station**: a receiver bolted to something that does not move, at a
  location that has been surveyed precisely in advance. It knows its own
  coordinates to the centimetre.
- A **rover**: the receiver that is actually going somewhere — on a survey pole,
  a tractor, a drone.

```
                      *       *       *          GPS satellites
                       \      |      /
                        \     |     /            the same signals,
                         \    |    /             carrying the same errors
        ~~~~~~~~~~~~~~~~~~\~~~|~~~/~~~~~~~~~~~~~~~~~~~~~~~~
              atmosphere   \  |  /   (slows both of them, equally)
        ~~~~~~~~~~~~~~~~~~~~\~|~/~~~~~~~~~~~~~~~~~~~~~~~~~~
                             \|/
                    +---------+                +---------+
                    |  BASE   | =============> |  ROVER  |
                    +---------+   corrections  +---------+
                  bolted down,                  on a pole,
                  knows exactly                 a tractor,
                  where it is                   a drone

                  "the errors right      "thanks - subtracting
                   now are THIS big"      them from mine"
```

The base watches the same satellites as the rover. Because it knows where it
really is, it can compute what the satellite distances *should* be, compare them
to what it is actually measuring, and derive the error in each one. It packages
those corrections up and streams them to the rover continuously — over a radio
link, or the internet, or a phone connection.

The rover applies the corrections and the shared error cancels out. Instead of a
few metres, you get one to two centimetres.

This is not exotic kit. Farm equipment uses it. Construction sites use it.
Surveyors use it all day. Drone mapping depends on it.

### The linchpin

Read that again and notice what the whole scheme rests on: **the base station
knowing exactly where it is.**

RTK does not really measure where the rover is. It measures the *distance and
direction from the base to the rover*, very precisely, and then adds that to
where the base says it is.

So if the base station's stated coordinate is wrong by two metres, the geometry
is still perfect — the rover measures its offset from the base beautifully — but
every position it produces is shifted by exactly those two metres. The rover has
accurately measured its distance from a lie.

Nothing about that looks like an error. The measurements are all clean and
consistent. The rover's own confidence checks pass, because they are checking
the quality of the measurements, and the measurements *are* good. It is only the
starting point that is wrong.

That is the target.

## Part 3: The software

RTKLIB is an open-source library that implements all of this. It was written by
a Japanese academic, Tomoji Takasu, and it is genuinely excellent — for a long
time it was the only way to do serious RTK without buying proprietary equipment.

It is also everywhere. It ships in Windows applications that surveyors run. It
is packaged by Linux distributions. A popular fork called "demo5" is what most
hobbyists with low-cost receivers use. And its code has been copied into
commercial GPS products.

One more fact matters: **the stable branch has not received a commit since
December 2020.** The project is, in practice, unmaintained.

## Part 4: The message

The base station talks to the rover in a format called RTCM3. Most of the
messages are corrections — satellite by satellite, here is how wrong your
distance measurement is.

But a few messages are just housekeeping. Message **type 1033** is one of these.
It carries five pieces of text describing the base station's hardware:

- the antenna model
- the antenna serial number
- the receiver model
- the receiver firmware version
- the receiver serial number

Nothing but labels. `TRIMBLE NETR9`, that sort of thing. Nobody navigates by
them.

Because these are text of varying length, the format uses a common trick. Each
string is sent as **a length, then that many characters**. So the receiver reads
one byte that says "the next thing is 13 characters long", then reads 13
characters. Like an envelope with the page count written on the outside.

That length byte is a single byte, so it can say any number from 0 to 255.

Hold that thought.

## Part 5: The bug

Inside RTKLIB there is a place to put each of those five strings. The receiver
model, for example, gets a slot 64 characters wide. That is generous; real
receiver names are far shorter.

The code does something careful and then something careless.

**The careful bit:** when it reads the characters off the wire, it uses a
temporary holding area of 32 characters and it explicitly refuses to read more
than 31 of them. However big a number the attacker writes on the envelope, only
31 characters ever get read in.

**The careless bit:** when it then copies that text into the permanent 64-character
slot, it uses **the length the attacker declared** — not the amount it actually
read, and not the size of the slot.

So an attacker sends a message that says "the receiver model is 255 characters
long," and the program dutifully copies 255 characters into a space built for
64. It runs off the end by about 190 characters and keeps writing into whatever
happens to sit next in memory.

```
  memory:  receiver-model slot      other fields        BASE COORDINATES
           |<--- 64 bytes --->|                       |<-X-><-Y-><-Z->|
          +-------------------+----------------------+-----+-----+-----+
          | TRIMBLE NETR9     |  serial, version...  |     |     |     |
          +-------------------+----------------------+-----+-----+-----+
           ^                  ^                            ^
           |                  |                            |
           |   the slot ends here                          |
           |                                               |
           |<===== "I am 255 characters long" =============>|
                 31 real       then zeros, zeros, zeros...
                 characters
```

That is a buffer overflow, and a security firm called FuzzingLabs found and
reported it, along with three similar ones, in June 2026.

### Why it looks boring

If you have any security background, your instinct now is that this is a
takeover — overflow a buffer, overwrite something important, take control of the
machine. That instinct is wrong here, for two reasons.

**Everything written past the end is zeros.** The copying function stops at the
end of the real text and then pads the rest of the declared length with zeros.
Since at most 31 real characters were ever read in, everything beyond that is
zero-fill. The attacker cannot write chosen values out of bounds. They can only
*erase*.

Think of it as an eraser rather than a pen. You choose where the erasing starts
and how far it goes, and that is all you choose.

**And it never escapes its container.** The 64-character slot sits inside a much
larger structure — around 240 kilobytes of it. Even the worst case only reaches
a few hundred bytes past the slot, which is still deep inside that structure.
There is nothing there worth hitting. No return addresses, no function pointers,
none of the machinery an exploit would need.

So: a bug that writes zeros into the middle of a large object it cannot get out
of. Automated memory-checking tools report nothing at all for the case I care
about, because in that case nothing technically goes out of bounds.

Boring.

Except for what happens to be sitting a couple of hundred bytes past the
receiver-model slot.

## Part 6: What the zeros land on, and what a mantissa is

They land on the base station's coordinates.

Remember Part 2: the coordinate of the base station is the number the entire
system trusts. Those three numbers — an X, Y and Z position in a coordinate
system centred on the Earth — sit in memory a couple of hundred bytes past the
receiver-model text. Well within reach.

Now, an attacker who could write *chosen* values there would simply type in a
new location. But we established that this attacker can only write zeros. So
what does erasing part of a number actually do to it?

This is the part that turns a boring bug into an interesting one, and it needs a
short detour into how computers store numbers with decimal points.

### Scientific notation, in binary

You already know scientific notation. Instead of writing

    3,978,242.4348

you write

    3.9782424348 × 10⁶

Two separate pieces of information: **the digits** (3.9782424348) and **where
the decimal point goes** (10⁶). Move the point around, and you can write
enormous numbers or tiny ones using the same handful of digits.

Computers store decimal numbers exactly this way, but in binary. The format is
called a *double*, it occupies 8 bytes, and those 8 bytes are divided into three
parts:

| part | size | what it does |
|---|---|---|
| sign | 1 bit | positive or negative |
| **exponent** | 11 bits | where the point goes — the overall scale |
| **mantissa** | 52 bits | the actual digits |

The **mantissa** is just the fancy word for "the digits." It is the significant
part of the number, stripped of any information about how big the number is. The
exponent handles bigness; the mantissa handles precision.

Fifty-two binary digits is a lot of precision. For a number around four million
— which is roughly what our coordinate is, measured in metres — those 52 bits
let you specify a position down to about a *billionth of a millimetre*. Far
finer than anyone needs.

### Now erase some digits

Here is the crucial detail. On essentially every computer you will meet, the
8 bytes of a double are stored with the **least important digits first**. So
when our attacker's eraser sweeps through, the first thing it destroys is the
fine detail — and only as it continues does it start eating the digits that
matter.

```
  one coordinate = one double = 8 bytes

   byte 0     1     2     3     4     5     6     7
      +-----+-----+-----+-----+-----+-----+-----+-----+
      |     |     |     |     |     |     |     |     |
      +-----+-----+-----+-----+-----+-----+-----+-----+
      |<------- mantissa: the digits ------->|<-exp->|s|
      |                                      |
      | finest detail            coarsest detail
      | (billionths of a mm)     (metres, then hundreds of metres)
      |
      +-- the eraser starts HERE and works rightwards
          so precision is destroyed from the bottom up
```

Each byte erased wipes out 8 binary digits of precision. The number does not
become garbage. It becomes a **rounder version of itself**.

Picture a ruler marked in millimetres. Rub out every tenth marking and you can
now only report positions to the nearest centimetre. Rub out more and you are
down to the nearest 10 cm, then the nearest metre. The ruler still works. It
still gives you sensible-looking answers. The answers are just coarser, and
anything between the surviving marks gets snapped to a mark.

Here is that idea on an actual number line, using the real coordinate from my
test data. The base station's true X position is `-3,978,242.4348` metres:

```
  FULL PRECISION - every fine gradation still present

    -3978244        -3978243        -3978242        -3978241
   -----|---------------|---------------|---------------|----->
                                 x
                                 |
                                 +--- true position of the base:
                                      -3978242.4348


  ERASE 4 BYTES - only every 2 metres survives

    -3978244                        -3978242
   -----|-------------------------------|---------------------->
                                 x      |
                                 |      |
                                 +----->+
                                  snaps to the nearest
                                  surviving mark, downwards

                                  new coordinate: -3978242.0000
                                  the base has "moved" 0.43 m
```

Note which way it moves. Erasing digits always rounds the number *towards zero*,
so the attacker does not even choose the direction — that falls out of the base
station's own coordinates.

Running that for every number of erased bytes, on the same real coordinate:

| bytes erased | mantissa digits left | resulting grid | coordinate becomes | error |
|---|---|---|---|---|
| 1 | 44 | 0.0000002 mm | −3978242.4348 | none you could measure |
| 2 | 36 | 0.03 mm | −3978242.4348 | none you could measure |
| 3 | 28 | 8 mm | −3978242.4297 | **5 mm** |
| 4 | 20 | **2 m** | −3978242.0000 | **0.43 m** |
| 5 | 12 | 512 m | −3978240.0000 | **2.43 m** |
| 6 | 4 | 131 km | −3932160.0000 | 46 km |

Each extra byte erased multiplies the coarseness by 256, because that is what
eight more binary digits does. The coordinate gets snapped down to the nearest
multiple of the grid spacing.

Two things follow, and they are what make this attack practical.

**The attacker chooses the scale, not the value.** They cannot say "move it two
metres north." They can only say "round it off this hard." Where it lands then
depends on the base station's actual coordinates — which they may not know.

**But one of those rungs is universal.** Look at the row where the grid becomes
2 metres. Whatever the base station's true coordinate is, rounding it down to
the nearest multiple of 2 metres moves it by *somewhere between zero and two
metres*. Always. The attacker does not need to know anything about the base
station to guarantee an error of that size. Below that rung the error is too
small to matter; above it, the error gets so large that the receiver stops
producing a confident answer at all and the attack becomes obvious.

There is a narrow band where the damage is big enough to matter and small enough
to stay invisible, and it is reachable without knowing anything about the target.

*(I am describing the mechanism, not publishing the lookup table of which
declared lengths produce which rungs. Anyone determined can derive it from public
source code in an afternoon, but there is a difference between derivable and
handed over.)*

## Part 7: The message that triggers its own damage

There is one more piece, and it is what makes this a live attack rather than a
curiosity.

When RTKLIB finishes decoding a type 1033 message, it reports back "this was an
antenna information message." The real-time server sees that report and responds
by taking the base station coordinates out of the message and adopting them as
the reference for all future position calculations.

Without checking them.

So a single message does both halves of the job: it corrupts the coordinate, and
it causes the corrupted coordinate to be put into service. No second message, no
waiting.

And here is the detail I keep coming back to. RTKLIB has a second code path for
processing recorded data after the fact, rather than live. **That path checks.**
Before adopting a base position it verifies the coordinate is not obviously
broken.

Somebody thought about this problem. The check went into the path that reads a
file on your desk after the flight, and not into the path that takes bytes off a
radio in real time.

## Part 8: What the receiver does about it

Nothing. That is the finding, and it took me a while to believe it.

I ran a clean data set and an attacked one all the way through, and compared
every single position the receiver produced:

| | clean | attacked |
|---|---|---|
| positions produced | 85 | 85 |
| flagged "RTK FIXED" (best quality) | 17 | 17 |
| flagged "float" (second best) | 68 | 68 |
| any quality flag different, at any moment? | — | **no** |
| how far the position moved | — | **2.435 m** |

The injected error was 2.435 metres. The rover's reported position moved by that
amount, exactly, and **the quality flags were identical** — same count, same flag
at every single moment in the run. No dropouts. No degradation. No rejection.

The receiver emits a position nearly two and a half metres from the truth, while
reporting precisely the confidence it reports when everything is perfect.

It does not notice because there is nothing to notice. Its quality flags describe
how well it solved the geometry, and it solved the geometry beautifully. It has
no way to question the starting point it was handed.

## Part 9: The logs are watching the wrong thing

"Nothing is logged" is nearly true, and the precise version is worse.

RTKLIB does have a diagnostic log, and the type 1033 decoder does write to it.
Turn the logging all the way up and you get one line per antenna message,
recording the text it received.

That line cannot show the attack. It prints the *temporary holding buffer* — the
one capped at 31 characters. So the log faithfully records up to 31 characters of
attacker-chosen text, which the attacker can make look completely ordinary. A
message declaring a length of 255 produces a log line indistinguishable from a
normal one.

**The declared length — the number that causes all the damage — is never written
to any log, at any verbosity setting.**

And the step that actually does the harm, taking the corrupted coordinate and
putting it into service, has no logging at all. The only trace is a counter
ticking up by one.

So: at default settings, nothing. With diagnostics compiled in and turned to
maximum, an operator gets one line recording a plausible-looking antenna name,
and still no record that the base station's coordinates changed.

The instrument exists. It is pointed in the wrong direction.

## Part 10: The compiler setting, and the thing I got wrong

Now for the part that surprised me, because I predicted it wrongly in writing and
had to correct myself.

Modern C compilers have an optional safety feature. Switch it on and, for certain
common operations, the compiler inserts a check: *does this copy actually fit
where it is going?* If it does not fit, the program deliberately kills itself
rather than continue.

The copy in this bug is exactly the kind that gets checked. So with that feature
active, this bug does not corrupt anything. The program simply dies. One message
is a remote crash — bad, but loud and obvious.

I assumed the world divided along an obvious line: Windows applications built
without the feature would corrupt silently, and Linux builds would have it and
would crash. Linux distributions have formal policies requiring this hardening.
Embedded receivers run Linux. I wrote that prediction down.

It is wrong. **Every build I have measured corrupts silently.**

**Both Windows distributions.** I downloaded the official Windows tools and the
popular demo5 fork, fed them the malicious message, and watched them write a
corrupted base station coordinate into their own output files. Exit code zero, no
complaint. And this is not a safety check somebody forgot to enable — the feature
belongs to the GNU C library, and these are built with a different compiler
against different libraries where it does not exist to enable. It was never on
the menu.

**Debian's own package.** This is the one that killed my prediction. Debian
packages RTKLIB, at exactly the version I had been studying, built for every
processor architecture they support. I pulled the ARM build apart and looked for
the hardened functions.

There are none. Not one, anywhere in the binary. The ordinary unchecked versions
are all present. Debian's package escapes the hardening its own policy nominally
requires — most likely because RTKLIB's build files override the compiler
settings the distribution tries to inject.

So installing this from your Linux distribution, on ARM, lands in the silent
corruption column alongside everything else.

The crash is what you get by compiling the software yourself with the right
settings. It is not what anybody ships.

*(One footnote for the suspicious: the internal layout that determines exactly
which erasures reach the coordinate turns out to be identical across every
processor architecture I checked — six of them, 32-bit and 64-bit alike. The same
malicious message works everywhere without adjustment.)*

## Part 11: Flying it

Simulated positions on a screen only get you so far. I wanted to know what a
vehicle does.

So I built a loop: a simulated drone's true position feeds a synthetic GPS
signal generator, which feeds RTKLIB, which produces a position, which is fed
back to the drone's autopilot as its only GPS. The malicious message gets spliced
into the correction stream mid-flight, exactly as it would arrive over a radio
link. The drone's flight controller then computes its own false position from the
corrupted data and flies on that.

```
        real base station                    ATTACKER
        (legitimate corrections)             (one fake antenna-name message)
                  |                                |
                  |                                |
                  +--------------+-----------------+
                                 |
                                 v
                        unauthenticated radio link
                                 |
                                 v
                        +------------------+
                        |     RTKLIB       |  <-- base coordinate corrupted
                        +------------------+      here, and adopted here
                                 |
                              position
                                 |
                                 v
                        +------------------+
                        |    autopilot     |
                        +------------------+
                                 |
                                 v
                           vehicle moves
                                 |
        +------------------------+
        |   (and its true position becomes the
        v    input to the GPS simulation, closing the loop)
```

Nothing is patched in by hand. The aircraft's own position is what the simulated
satellites are computed from, and RTKLIB's output is the aircraft's only GPS — so
a corrupted base coordinate propagates all the way round into the flight control
loop and back out again.

I flew it twice. Same aircraft, same flight plan, same malicious message. The
only difference was which version of RTKLIB was in the loop.

### The version everyone runs

The drone took off, hovered, received the malicious message, and carried on. When
told to fly to a specific point 30 metres away it flew there, announced arrival,
and landed normally.

It was 1.4 metres from where it believed it was.

Its flight log contains **zero errors**. Not one warning, not one anomaly. GPS
quality reported as the highest possible value from takeoff to touchdown, without
a flicker.

### The version that crashes

Same flight, hardened build. The malicious message arrives while the drone is
hovering:

```
87.5 s   GPS quality: BEST -> NONE        (RTKLIB has just died)
91.4 s   ERROR: EKF primary changed
91.5 s   ERROR: EKF variance
91.5 s   ERROR: navigation failsafe
91.5 s   MODE -> LAND                     "EKF Failsafe: changed to Land Mode"
105.9 s  SmartRTL deactivated: bad position
120.6 s  Hit ground at 0.50 m/s
122.7 s  Disarming motors
```

Four seconds from losing GPS to declaring an emergency. Thirty-three seconds from
losing GPS to sitting on the ground, descending at half a metre per second, which
is a landing rather than a fall. It abandoned the route it was flying. It logged
four distinct errors while doing it.

### Which is worse?

Instinct says the crash. Instinct is wrong, and this is the most transferable
thing I have to say.

Every autonomous system is built to handle *"my sensor stopped working."* That is
an expected condition with a plan attached: raise an alarm, stop, hand back
control, land. Here it fired in four seconds and the aircraft put itself down
safely.

Essentially nothing is built to handle *"my sensor is confidently wrong,"* because
there is no signal to react to. No alarm can fire when every reading looks
perfect.

So on the question of *whether anyone finds out*, the version that crashes wins
outright — and it is the version nobody ships.

## Part 12: But the crash is its own attack

I nearly stopped there, and stopping there would have been wrong. Look again at
one line from the crashed drone's log:

```
105.9 s  SmartRTL deactivated: bad position
```

With no position, the drone **could not fly home**. It did not know where home
was. Landing immediately was not one option among several — it was the only thing
available to it.

Now ask who decides *when* that happens.

The attacker does. It happens the moment they transmit. So an attacker who can
see the target can wait until it is over a lake, or a river, or the far side of a
fence, and then send one message to bring it down there.

I measured how well that can be aimed. With no position estimate the drone has no
way to hold station, so it drifts for the whole descent:

| | |
|---|---|
| height when the emergency fired | 15 metres |
| descent | 29 seconds |
| **sideways drift before touchdown** | **10.13 metres** |
| character of the drift | one direction, never corrected |

So the attacker selects a **circle tens of metres across**, not a spot. Good
enough for a lake or a field. Not good enough for a specific lane of traffic.

And 10 metres is the **best case**. The simulation had no wind, the drone was
low, and it was nearly stationary when it was hit. Wind, height, or a moving
target all make it worse. One run is one measurement, not a guarantee.

A human watching can still rescue it — the aircraft flies fine by hand once you
stop asking it where it is, and the alarms are loud. An automated flight with
nobody watching cannot be rescued.

### Two weapons, and no safe option

The honest way to put this is that the two builds hand an attacker **different
tools**. Neither one is the harmless case.

```
                    ONE MALICIOUS MESSAGE
                             |
              +--------------+--------------+
              |                             |
       build without the            build with the
       safety check                 safety check
       (what everyone ships)        (compile it yourself)
              |                             |
              v                             v
       coordinate quietly            the program dies
       wrong by ~2 m                        |
              |                             v
              v                      aircraft loses GPS,
       vehicle flies on,             cannot fly home,
       reports success,              lands within ~10 m
       logs ZERO errors              of the attacker's choosing
              |                             |
              v                             v
      +----------------+           +------------------+
      | SILENT ATTACK  |           |   LOUD ATTACK    |
      | on ACCURACY    |           | on AVAILABILITY  |
      +----------------+           +------------------+
       nobody finds out             everybody finds out,
                                    but it is on the ground
```

| | the version that ships | the hardened version |
|---|---|---|
| what it does | moves the reported position | brings the aircraft down |
| precision | exact, attacker's choice | ~10 m, or worse |
| magnitude | ~2 m before it starts looking wrong | total — it stops flying |
| does anyone notice? | **no** | yes, immediately |
| useful for | quietly ruining survey data, agriculture, landing accuracy, for as long as you like | taking an aircraft out of the air at a chosen moment |

Which leads somewhere uncomfortable. **If your goal is to put a drone in a lake,
the hardened build is the better tool for the job.** Two metres of silent error
will not do it. A forced landing will.

Turning on the compiler's safety feature does not fix this bug. It exchanges a
quiet attack for a loud one. That is a trade genuinely worth making if what you
care about is knowing you were attacked — which is most people, most of the time
— but it should be described as what it is.

## Part 13: The actual fix

Five lines. Refuse to believe the declared length if it is bigger than what was
actually read:

```c
if (n >31) n =31;
if (m >31) m =31;
if (n1>31) n1=31;
if (n2>31) n2=31;
if (n3>31) n3=31;
```

The holding buffers are 32 characters, so this only stops the copy from claiming
more than ever arrived. I built the software with and without this change and ran
the same data through both: the attacked streams come back at the true
coordinate, and legitimate messages decode identically, so the change costs
nothing that a real base station would notice.

I have not filed it as a patch yet. I posted the analysis publicly on the bug
report a few days ago and I am waiting to see whether anyone responds first.

## Part 14: Where this actually stands

None of this is a secret. The bugs were reported publicly in June 2026 and the
analysis has been public since.

All four reports are still open and unpatched. Each carries a single comment from
the person who found them, offering to file the paperwork for an official
vulnerability identifier and asking the maintainer how they would like to handle
it. There has been no reply in seven weeks.

The demo5 fork shipped a new release **thirteen days after** the bugs were made
public, with the flaw untouched.

So "wait for the patch" is not advice that means anything here. There is nobody
to wait for. I would rather say that plainly than imply a fix is on its way.

The same code is also present, unchanged, in at least one commercial GPS
manufacturer's public fork of RTKLIB — same flaw, same internal layout, same
missing check on the live path. That is an observation about published source
code. I have not examined any actual device's firmware, and until I do, the
honest statement is that *the source is affected*, not that any product behaves
any particular way.

## Part 15: What I did not do

Worth being blunt about, because a lot of security writing is vaguer here than it
should be.

- **No real hardware was involved anywhere in this work.** No aircraft, no GPS
  receiver, no radio transmitted. All of it is simulation and recorded data.
- **One base station, one rover, one data set**, and an old one. Whether the same
  invisibility holds across other satellite constellations and modern
  multi-frequency receivers is untested.
- **The drone results are one flight each.** One airframe, one flight profile,
  stock settings. A different vehicle or different emergency-response settings
  would give different numbers. The *direction* of the result is the claim; the
  exact seconds are illustrative.
- **The 10-metre landing dispersion is a single sample in zero wind.** Treat it
  as a floor, not a bound. A real figure would need many runs across different
  heights and wind conditions, which I have not done.
- **The size of the error depends on the specific base station**, because what is
  being erased is the digits of its particular coordinate.

## Why I think it matters

The bug itself is small and the fix is five lines. What is interesting is the
shape of it.

Every safety check in this system is aimed at the quality of the measurements.
Are the satellites healthy? Is the geometry good? Did the maths converge? All of
those checks passed, throughout, in every attacked run I did — because the
measurements really were fine.

Nothing checks the *assumption* the measurements are built on. The base station's
coordinate arrives over an unauthenticated link, gets adopted without a glance,
and every downstream check then dutifully confirms that the arithmetic performed
on it was correct.

That is not unique to GPS software. It is what most systems look like: heavily
instrumented at the point where errors are expected, and completely blind at the
point where a value is simply taken on faith.

---

*Corrections welcome. Everything above is reproducible, and if you can show me a
shipped build that lands in the crash column, I would genuinely like to hear
about it — I have not found one.*
