# 6. Circulation methods

Both standard methods hold bottomhole pressure constant. They differ only in
*when* the mud gets weighted up.

## Driller's Method — two circulations

**First circulation:** get the influx out using the mud already in the hole.
Hold drill pipe pressure constant at ICP for the whole circulation.

**Then** weight up.

**Second circulation:** displace the well to kill mud. Take drill pipe pressure
down the schedule from ICP to FCP, then hold FCP until kill mud is at surface.

```python
from wellcontrol import examples
sheet = examples.vertical_land_well_kill_sheet()

for stage in sheet.drillers_method():
    print(f"{stage.name} — {stage.strokes:.0f} strokes")
    print(f"  {stage.description}\n")
```

```
First circulation - remove the influx — 4017 strokes
Weight up — 0 strokes
Second circulation - displace to kill mud — 1466 strokes
Second circulation - kill mud to surface — 4017 strokes
```

**Why it is simple:** the first circulation is a single instruction — hold the
drill pipe gauge on one number. No schedule, no interpolation, nothing to get
wrong while under pressure. It also starts immediately, with no waiting.

**Why it costs:** roughly 9,500 strokes against 5,482 for Wait and Weight. And
throughout the first circulation the annulus still holds original-weight mud,
so the casing shoe carries higher pressure for longer.

## Wait and Weight — one circulation

Also called the Engineer's Method or One Circulation Method.

Weight the mud up **first**, with the well shut in. Then kill it in a single
circulation: kill mud goes down the string while the influx comes up the
annulus.

```python
for stage in sheet.wait_and_weight():
    print(f"{stage.name} — {stage.strokes:.0f} strokes")
```

```
Weight up — 0 strokes
Circulate to bit — 1466 strokes
Circulate to surface — 4017 strokes
```

**Why it is better on paper:** one circulation instead of two, and lower peak
casing pressure, because kill mud entering the annulus behind the influx adds
hydrostatic before the gas reaches surface.

### The shoe-pressure advantage is conditional — check it

Wait and Weight is widely said to put less pressure on the casing shoe. The test
is one comparison:

> **Open hole annular volume vs drill string volume.**
> Larger open hole → Wait and Weight genuinely lowers the pressure at the shoe.
> Smaller → no advantage at all.

The reasoning: kill mud only starts helping at the shoe once it has come round
the bit and into the annulus, which takes one *string volume* of pumping. The
influx reaches the shoe after roughly the *open hole annular volume* has been
pumped. The heavy mud gets there first only when the open hole holds more than
the string does.

```python
open_hole = sheet.annulus.volume_between(7000, 10000)        # 127.6 bbl
string    = sheet.annulus.string.internal_volume_bbl         # 171.6 bbl
```

On the reference well the open hole is **smaller**, so there is no advantage —
the simulation gives an identical peak shoe pressure of 4,154 psi for both
methods. Pull the bit up to 6,000 ft and the open hole (210.6 bbl) exceeds the
string (100.5 bbl), and Wait and Weight comes out 26 psi lower.

The `wait_and_weight` plan computes which case applies and says so in its notes.

```python
from wellcontrol.methods import plan_kill
from wellcontrol import examples
from wellcontrol.wellconfig import WellConfiguration, BOPLocation, Trajectory

well = examples.well_state(
    WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL))

plan_kill(well, "drillers").peak_shoe_pressure_psi          # 4154
plan_kill(well, "wait_and_weight").peak_shoe_pressure_psi   # 4154
plan_kill(well, "drillers").peak_casing_pressure_psi        # 1100
plan_kill(well, "wait_and_weight").peak_casing_pressure_psi #  996
```

The casing-pressure advantage is real (1,100 → 989 psi). The shoe advantage is
not, on this well.

### Careful which shoe number you compare

Peak shoe pressure over the whole operation is often set **at shut-in, before
any pumping** — and shut-in is a property of the well, identical whichever
method you pick. Comparing peaks that include it can show two methods as
identical when their circulating behaviour differs:

```python
plan = plan_kill(well, "wait_and_weight")

plan.shut_in_shoe_pressure_psi              # 4154 — same for every method
plan.peak_circulating_shoe_pressure_psi     # 4115 — the discriminator
plan.peak_shoe_pressure_psi                 # 4154 — dominated by shut-in
```

Against Driller's, the circulating peaks are 4,115 vs 4,120 psi. Small here, but
real — and the overall peak hides it entirely.

Why is shut-in the worst moment? As the gas rises out of the tight collar
annulus (0.0836 bbl/ft) into the wider casing annulus (0.1203 bbl/ft) it gets
**shorter** despite expanding — the annulus widens ~44% while the gas expands
~33%. More hydrostatic below the shoe means less pressure on it. The textbook
"worst moment is gas at the shoe" assumes a uniform annulus.

**Why it costs:** the well sits shut in while the mud is weighted up. If gas is
migrating, that wait is not free — surface pressure climbs the whole time. It
also demands more of the mud system and more of the crew, who must follow a
schedule rather than hold one number.

## Choosing

| Situation | Leans toward |
| --- | --- |
| Gas migrating, pressures rising | Driller's — start now |
| Mud system slow to weight up | Driller's |
| Crew inexperienced / high stress | Driller's — simpler |
| Shoe strength marginal | Wait and Weight — lower shoe pressure |
| Large influx | Wait and Weight — less time with a light annulus |
| Deep well, long circulation | Wait and Weight — halves the exposure |

In practice many operators default to Driller's Method for its simplicity and
immediacy, and reserve Wait and Weight for wells where shoe pressure is the
binding constraint. Some use a **Concurrent Method** — start circulating
immediately and weight up on the fly — which gets some of both benefits at the
cost of being the hardest to execute.

Whatever is chosen, the shape of the answer is the same: constant bottomhole
pressure, drill pipe gauge on schedule, choke doing the work.

## What the choke operator sees

Understanding the shape of the casing pressure curve prevents panic.

**Driller's, first circulation.** Casing pressure rises steadily as gas comes up
and expands. It peaks just as the gas reaches surface, then drops sharply as gas
is bled off. The peak can be several times the original SICP. This is normal.

**Wait and Weight.** Casing pressure follows a similar shape but peaks lower,
because kill mud is already entering the annulus behind the influx.

**Both.** Once the influx is out and the annulus is full of kill mud, casing
pressure should read zero. If it does not, the well is not dead — either the
mud is not heavy enough, or there is a second influx.

The end-of-kill check is the same either way: shut down, shut in, and watch. Zero
on both gauges and no flow means the well is dead.

## When it goes wrong

**Drill pipe pressure too high.** Bottomhole pressure is above formation
pressure — risk of breaking down the shoe. Open the choke.

**Drill pipe pressure too low.** Bottomhole pressure is below formation
pressure — the well is taking another influx. Close the choke.

**The choke plugs.** Casing pressure spikes. Switch to the redundant choke.
Every choke manifold has two for this reason.

**Pump fails mid-kill.** Shut in and record the pressures. Recalculate from the
new shut-in readings before resuming — the well has moved on and the old
schedule no longer applies.

**Losses at the shoe while killing.** The hardest case, because the cures are
opposite: the kick wants more pressure and the losses want less. There is no
clean answer from the kill sheet; this becomes a
[kick tolerance](07-kick-tolerance.md) problem and usually a decision above the
rig floor.

## Volumetric method — when you cannot circulate

If the string is off bottom, plugged, or out of the hole, there is no way to
circulate and no drill pipe gauge to follow.

The volumetric method controls the well by bleeding **measured volumes** of mud
while letting migrating gas expand, keeping bottomhole pressure roughly constant
without circulating. It buys time, it does not kill the well — it holds the
situation while a route to circulation is restored, typically by stripping pipe
back to bottom.

It is a genuinely different technique with its own procedure, and worth studying
separately once the constant-bottomhole-pressure methods are solid.

---

Previous: [The kill sheet](05-kill-sheet.md) · Next: [Kick tolerance and MAASP](07-kick-tolerance.md)
