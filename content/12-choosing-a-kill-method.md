# 12. Choosing a kill method

Seven methods, four well configurations. Not all combinations work, and the ones
that don't fail for reasons worth understanding.

## The methods

| Method | Circulates? | Used when |
| --- | --- | --- |
| **Driller's Method** | Yes, twice | Standard. Start immediately, weight up later. |
| **Wait and Weight** | Yes, once | Standard. Weight up first, kill in one pass. |
| **Volumetric Method** | No | Cannot circulate; gas migrating. |
| **Stripping to Bottom** | No | Bit off bottom. Restores the circulation path. |
| **Lube and Bleed** | No | Cannot circulate; gas already at surface. |
| **Reverse Circulation** | Yes, backwards | Keeping the influx away from the casing shoe. |
| **Bullheading** | No | Cannot, or must not, bring the influx up. |

Stripping is the odd one out: it is not a kill, it is the intervention that makes
a kill possible. See [Stripping and snubbing](13-stripping.md).

```python
from wellcontrol.methods import list_methods, plan_kill
from wellcontrol import examples
from wellcontrol.wellconfig import WellConfiguration, BOPLocation, Trajectory

well = examples.well_state(
    WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL))

plan = plan_kill(well, "wait_and_weight")
print(plan.format_summary())
for stage in plan.stages:
    print(stage.name)
```

## The applicability matrix

Computed by the library, not asserted here:

```python
from wellcontrol.methods import applicability_matrix

for key, verdict in applicability_matrix(well).items():
    print(key, "usable" if verdict.usable else "BLOCKED")
```

| Method | Surface / Vertical | Surface / Horizontal | Subsea / Vertical | Subsea / Horizontal |
| --- | :---: | :---: | :---: | :---: |
| Driller's Method | ✅ | ✅ | ✅ | ✅ |
| Wait and Weight | ✅ | ✅ | ✅ | ✅ |
| Volumetric | ✅ | ❌ | ❌\* | ❌ |
| Stripping to Bottom | ✅† | ✅† | ✅† | ✅† |
| Lube and Bleed | ✅ | ❌ | ✅ | ❌ |
| Reverse Circulation | ✅ | ✅ | ✅ | ✅ |
| Bullheading | ✅ | ✅ | ❌\* | ✅ |

\* Blocked on the *reference wells* for a strength reason, not a physics
reason — a different shoe or mud weight changes the answer. The blocks in the
horizontal column are physics and do not change.

† Only when the bit is **off bottom**. With the bit on bottom there is nothing
to strip and the well can simply be circulated, so the method blocks itself.

### Why the horizontal column is empty for two methods

**Volumetric and Lube-and-Bleed both depend on gas migrating upward.** Gas rises
because it is buoyant, and buoyancy needs a vertical direction to act in. An
influx lying in a horizontal lateral has none.

```python
well = examples.well_state(
    WellConfiguration(BOPLocation.SURFACE, Trajectory.HORIZONTAL))

well.influx_height_md_ft     # 903 ft of measured length
well.influx_height_tvd_ft    # 0 ft of vertical height

plan_kill(well, "volumetric").applicability.blockers
# ['The influx has no vertical height -- it is lying in a horizontal or
#   near-horizontal section. Gas will not migrate, so there is nothing for
#   this method to track and no pressure rise to bleed against. ...']
```

This is not a modelling limitation, it is the well. The Volumetric Method works
by bleeding mud in response to a pressure rise caused by migration. No
migration, no pressure rise, nothing to respond to. The method has no way to
move the influx out of the lateral in the first place.

### Why bullheading is blocked on the subsea vertical well

Not physics — arithmetic:

```
Bullheading would put 8014 psi on the shoe against a fracture pressure
of 7894 psi -- 120 psi over. The shoe would break down before the influx
went away, turning a contained kick into an underground blowout.
```

Bullheading is **hardest at the start**: the influx is light, so the column
supplies the least hydrostatic, so surface pressure is highest — and so is the
pressure on the shoe. A stronger shoe or a heavier starting mud changes the
verdict.

## What the shoe pressure plot is for

A paper kill sheet gives you drill pipe and casing pressure. It does not tell
you what the *shoe* sees, and the shoe is what limits the well.

Peak shoe pressure on the reference vertical well, by method:

| Method | Peak shoe (psi) | vs fracture (4,677 psi) |
| --- | ---: | ---: |
| Reverse Circulation | 3,894 | 783 |
| Wait and Weight | 4,154 | 523 |
| Driller's Method | 4,154 | 523 |
| Volumetric | 4,250 | 427 |
| Bullheading | 4,354 | 323 |

Reverse circulation is lowest by a clear margin, and for a structural reason:
**the influx never passes the shoe.** It goes up the inside of the drill pipe
instead. On a well with marginal kick tolerance that can be the deciding factor.

## The Wait-and-Weight shoe advantage is conditional

Wait and Weight is widely taught as putting less pressure on the shoe. **That is
only true if kill mud reaches the annulus before the influx reaches the shoe**,
and on the reference well it does not:

```
Kill mud enters the annulus after ....... 171.6 bbl
Influx reaches the shoe after ........... 107.6 bbl
```

The influx gets there first, so both methods give an identical peak shoe
pressure of 4,154 psi. The casing-pressure advantage is real (996 vs 1,100 psi);
the shoe advantage is not, here.

The library computes which case applies and says so:

```python
plan = plan_kill(well, "wait_and_weight")
print(plan.notes[2])
# 'On this well the influx reaches the shoe after about 108 bbl, but kill mud
#  does not enter the annulus until 172 bbl have been pumped. ... Wait and
#  Weight gives NO shoe-pressure advantage here ...'
```

The test is: **string volume vs annular volume between shoe and TD.** A long
string below a shallow shoe loses the advantage; a short string below a deep
shoe keeps it. Check it for the well in front of you rather than assuming.

## Decision guide

Start here and work down:

1. **Can you circulate?**
   No, because the bit is off bottom → hold with Volumetric, **strip to bottom**,
   then circulate and kill conventionally.
   No, for any other reason → Lube and Bleed (gas at surface) or Bullhead (must
   not bring it up at all).

2. **Must the influx stay away from the shoe?**
   Kick tolerance marginal, and the string is open with no float →
   Reverse Circulation.

3. **Is gas migrating fast, or is the mud system slow?**
   Yes → Driller's Method. Start now, weight up during the first circulation.

4. **Otherwise** → Wait and Weight. One circulation, lower casing pressure.

And regardless of the answer, check the peak shoe pressure against the fracture
pressure before starting. That check is what the plots exist for.

## Using it

Interactively:

```bash
streamlit run app/streamlit_app.py
```

Or in code:

```python
from wellcontrol.methods import plan_kill
from wellcontrol.plotting import plot_kill

plan = plan_kill(well, "drillers")

if not plan.applicability.usable:
    for blocker in plan.applicability.blockers:
        print("BLOCKED:", blocker)

figure = plot_kill(plan, theme="light")
figure.savefig("kill.png", facecolor=figure.get_facecolor())
```

---

Previous: [MPD and underbalanced drilling](11-mpd-and-ubd.md) · Back to [index](README.md)
