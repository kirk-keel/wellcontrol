# 1. Fundamentals

## The one idea

A well stays under control when the pressure inside the wellbore is greater than
the pressure in the rock around it. That is the whole subject. Everything else
is bookkeeping about how to keep that true while the well is being drilled,
tripped, circulated, logged and cased.

When wellbore pressure falls below formation pressure, the formation pushes its
fluid into the well. That is a **kick**. A kick that reaches surface uncontrolled
is a **blowout**.

## Three pressures

**Formation pressure** (pore pressure) is what the fluid in the rock is pushing
with. It is a property of the rock, and nothing done at surface changes it.

**Hydrostatic pressure** is what the column of mud pushes back with. It depends
only on the density of the mud and the vertical height of the column:

```
P = 0.052 × MW × TVD
```

**Bottomhole pressure** is the total pressure at the bottom of the hole. It is
hydrostatic plus anything else acting on it:

```
BHP = hydrostatic + surface pressure + friction while circulating
```

Overbalanced means `BHP > formation pressure`. The well is quiet.
Underbalanced means `BHP < formation pressure`. The well flows.

## Barriers

Well control is organised around **two independent barriers** between the
formation and the atmosphere at all times.

The **primary barrier** is the mud column. It is the one doing the work every
minute of every day. Well control is overwhelmingly about keeping this barrier
intact, because the primary barrier failing is what produces every subsequent
problem.

The **secondary barrier** is the BOP stack. It is a fallback, not a plan. Closing
the BOP does not kill the well; it contains the well while you go about killing
it. A well that is shut in is still a well with a kick in it.

The distinction matters because it sets priorities. Almost all of well control
practice is about the primary barrier: monitoring it, maintaining it, and
noticing quickly when it starts to fail.

## Why wells go underbalanced

Only a handful of causes, and they are worth knowing by name because each has a
different countermeasure.

**Insufficient mud weight.** The mud was never heavy enough for the formation
being drilled. Usually a pore pressure prediction that came in low, or drilling
into an unexpected zone.

**Failure to keep the hole full.** Pulling pipe removes steel from the hole. If
the volume is not replaced with mud, the level falls and hydrostatic goes with
it. This is the single most common cause of kicks while tripping, and it is
entirely preventable by measuring what the hole takes and comparing it against
what it should take.

**Swabbing.** Pulling pipe too fast, or with a balled-up bit, drags the mud up
with the string and momentarily reduces bottomhole pressure. Unlike the previous
cause, swabbing leaves no volume discrepancy while it is happening — the kick
appears afterwards.

**Lost circulation.** Mud goes into a weak formation, the level in the annulus
falls, and hydrostatic falls with it. Losses and a kick at the same time is the
worst case in well control, because the two problems have opposite cures.

**Gas cutting.** Gas entrained in the returns reduces the density of the mud in
the annulus. Usually much less dangerous than it looks — because gas expands
mostly near surface where there is little hydrostatic left to lose, even heavily
gas-cut mud loses surprisingly little bottomhole pressure.

**Shutting the pumps down.** While circulating, friction in the annulus adds to
bottomhole pressure. Stop the pumps and that friction disappears. In a well with
a narrow margin, that alone can bring the well in — which is exactly the problem
managed pressure drilling exists to solve.

## Kick warning signs

Listed roughly in the order they usually appear. The earlier one is caught, the
smaller the influx and the easier everything that follows.

While **drilling**:

1. Drilling break — a sudden increase in rate of penetration
2. Increase in flow rate out with the pump rate unchanged
3. Increase in pit volume
4. Pump pressure drop with a pump stroke increase
5. Change in cuttings, or gas-cut mud
6. Increase in hookload
7. Well flows with the pumps off

While **tripping**:

1. Hole not taking the calculated fill volume
2. Hole giving back more than it should when running in
3. Well flows with the string static

```python
from wellcontrol.kick import DRILLING_KICK_INDICATORS, TRIPPING_KICK_INDICATORS

for i, sign in enumerate(DRILLING_KICK_INDICATORS, 1):
    print(f"{i}. {sign}")
```

Only the last item in each list is **positive** — a well that flows with nothing
moving it is definitely flowing. Everything above it is an indicator that
warrants a flow check, not a conclusion. The correct response to an indicator is
to stop and check, and the correct response to a positive flow check is to shut
the well in.

## Size matters enormously

The single most useful fact in well control is that **the difficulty of killing
a well scales with the size of the influx**, and the size of the influx scales
with how long it took to notice.

A 5 bbl kick and a 50 bbl kick are not the same problem ten times over. The
larger influx displaces more mud from the annulus, so it costs more hydrostatic;
it occupies more of the open hole, so it puts more pressure on the shoe; and if
it is gas, it expands proportionally more on the way out, so the choke has more
work to do at the worst moment.

This is why kick detection gets more attention than kick killing. Killing a
small kick is routine arithmetic. Killing a large one may not be possible within
the strength of the well.

## Units

Everything here is in API oilfield units:

| Quantity | Unit |
| --- | --- |
| Depth, length | ft |
| Diameter | in |
| Pressure | psi |
| Density | ppg (lb/gal) |
| Gradient | psi/ft |
| Volume | bbl (42 US gal) |
| Flow | gpm |
| Temperature | °F |

Conversions are in `wellcontrol.units` if you need metric.

```python
from wellcontrol import units

units.psi_to_bar(5000)      # 344.7
units.ppg_to_sg(12.0)       # 1.44
units.ft_to_m(10000)        # 3048.0
```

---

Next: [Hydrostatic pressure](02-hydrostatics.md)
