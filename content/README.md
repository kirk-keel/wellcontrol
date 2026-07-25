# Well control content

Theory paired with working calculations. Every formula here has a tested
implementation in `src/wellcontrol/`, and every worked example runs.

## Read in order

| # | Topic | Covers |
| --- | --- | --- |
| [1](01-fundamentals.md) | Fundamentals | Barriers, why wells go underbalanced, kick warning signs |
| [2](02-hydrostatics.md) | Hydrostatic pressure | `0.052 × MW × TVD`, EMW, ECD, tripping, slugs |
| [3](03-volumes-and-strokes.md) | Volumes and strokes | Capacities, annular overlay, pump output, position tracking |
| [4](04-kick-detection.md) | Kick detection and shut-in | SIDPP/SICP, influx identification, gas expansion, migration |
| [5](05-kill-sheet.md) | The kill sheet | KMW, SCR, ICP, FCP, pressure schedules |
| [6](06-circulation-methods.md) | Circulation methods | Driller's vs Wait and Weight, choosing, what goes wrong |
| [7](07-kick-tolerance.md) | Kick tolerance and MAASP | Leak-off tests, the drilling window, how big a kick survives |

## By well type

| # | Well type | The thing that changes |
| --- | --- | --- |
| [8](08-directional-wells.md) | Directional and horizontal | MD vs TVD; influx in a lateral has no vertical height |
| [9](09-subsea-wells.md) | Subsea | Choke line friction, mudline datum, riser margin |
| [10](10-hpht-wells.md) | HPHT | Mud density is not constant with pressure and temperature |
| [11](11-mpd-and-ubd.md) | MPD and UBD | Surface backpressure as a second, fast pressure lever |
| [12](12-choosing-a-kill-method.md) | Choosing a kill method | All seven methods, the applicability matrix, and why two cells are empty |
| [13](13-stripping.md) | Stripping and snubbing | Bleed volumes, the balance point, and what the drill pipe gauge reads off bottom |

## The three reference wells

| Well | Depth | Why it is here |
| --- | --- | --- |
| Vertical land | 10,000 ft MD/TVD | Every simple formula works |
| Horizontal | 12,000 ft MD / 5,910 ft TVD | MD/TVD confusion produces a badly wrong answer |
| Deepwater subsea | 15,000 ft TVD, 5,000 ft water | Choke line friction and riser margin dominate |

```python
from wellcontrol import examples

annulus, survey = examples.vertical_land_well()
sheet           = examples.vertical_land_well_kill_sheet()
tolerance       = examples.vertical_land_well_kick_tolerance()

annulus, survey = examples.horizontal_well()
sheet           = examples.horizontal_well_kill_sheet()

annulus, survey = examples.deepwater_subsea_well()
geometry        = examples.deepwater_geometry()
sheet           = examples.deepwater_kill_sheet(choke_line_friction_psi=350)
```

## The three things most worth remembering

1. **Pressure takes TVD, circulation takes MD.** The most consequential error in
   the subject. [→](08-directional-wells.md)
2. **Follow the drill pipe gauge, not the casing gauge.** The drill pipe is full
   of clean mud of known weight; the annulus is not. [→](05-kill-sheet.md)
3. **Detection beats technique.** Killing a small kick is arithmetic. Killing a
   large one may not be possible within the strength of the well.
   [→](04-kick-detection.md)

---

**These are engineering aids, not a substitute for certification, a company well
control manual, or the judgement of a competent person on the rig.**
