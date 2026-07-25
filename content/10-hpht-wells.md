# 10. HPHT wells

## Mud weight is not a constant

Everywhere else in this material, mud weight is a fixed number. In a high
pressure, high temperature well that assumption breaks down — in two directions
at once.

**Pressure compresses the mud**, making it denser with depth. At 15,000 psi an
oil-based mud is around 5% heavier than it was in the pit.

**Temperature expands it**, making it lighter with depth. At 350 °F the same mud
is around 7% lighter.

The two effects partly cancel. That is exactly what makes them dangerous —
partial cancellation makes it tempting to ignore both, and they do not cancel
evenly. Compression dominates in the deep, cool part of a well; expansion
dominates in the hot part. The net error can run to hundreds of psi in either
direction.

In a well whose drilling window is 0.5 ppg wide, several hundred psi is the whole
window.

## What counts as HPHT

Common industry thresholds:

- Bottomhole pressure above roughly **10,000 psi**
- Bottomhole temperature above roughly **300 °F** (150 °C)

Below those, the constant-density assumption is fine. Above them it is not, and
the well needs different equipment, different procedures and different
arithmetic.

## The density model

```
ρ(P,T) = ρ_ref × [1 + C_p × (P − P_ref) − C_t × (T − T_ref)]
```

```python
from wellcontrol.hpht import MudPVT

mud = MudPVT(
    surface_density_ppg=14.0,
    compressibility_per_psi=3.5e-6,
    thermal_expansion_per_f=2.6e-4,
)

mud.density_at(pressure_psi=15000, temperature_f=300)   # 13.90 ppg
```

Worked through:

```
14.0 × [1 + 3.5e-6 × 14985 − 2.6e-4 × 230]
= 14.0 × [1 + 0.0524 − 0.0598]
= 14.0 × 0.9926 = 13.90 ppg
```

Compression added 0.73 ppg. Expansion took away 0.84 ppg. Net: **0.10 ppg
lighter than the pit** — the well is very slightly weaker than the mud report
suggests.

### Oil-based muds are far more sensitive

Base oil is both more compressible and more thermally expansive than water:

```python
obm = MudPVT.typical(14.0, "oil_based")       # 3.5e-6 /psi, 2.6e-4 /°F
wbm = MudPVT.typical(14.0, "water_based")     # 2.7e-6 /psi, 1.7e-4 /°F

obm.density_at(15000, 350)    # 13.72 ppg — 0.28 ppg below the pit
wbm.density_at(15000, 350)    # 13.90 ppg — 0.10 ppg below the pit
```

Nearly three times the swing, from the same nominal mud weight.

Since most HPHT wells are drilled with oil-based or synthetic mud, the effect is
usually at its largest exactly where it matters most.

**These coefficients are representative, not authoritative.** Real HPHT work uses
PVT data measured on the actual mud system. A correlation is a planning tool.

## Temperature profile

```python
from wellcontrol.hpht import TemperatureProfile

profile = TemperatureProfile(surface_temp_f=70, gradient_f_per_100ft=1.5)
profile.temperature_at(20000)    # 370 °F

# Or fit to a measured bottomhole temperature
profile = TemperatureProfile.from_bottomhole(70, 370, 20000)
```

For a **subsea** well the datum is the mudline, not the rig floor — and the
seabed is cold (35–40 °F) regardless of latitude:

```python
profile = TemperatureProfile(
    surface_temp_f=40, gradient_f_per_100ft=1.5, datum_tvd_ft=5075
)
profile.temperature_at(15075)    # 190 °F
```

A deepwater well therefore has a *cold* upper section and a hot lower one, which
makes the density profile distinctly non-linear.

## Integrating the column

Density depends on pressure, and pressure depends on density. The library solves
them together, marching down the well:

```python
from wellcontrol.hpht import integrate_column, equivalent_static_density, pvt_error_psi

mud = MudPVT.typical(14.0, "oil_based")
profile = TemperatureProfile(70, 1.5)

for step in integrate_column(mud, profile, 20000, step_ft=4000):
    print(f"{step.tvd_ft:>7.0f} ft  {step.temperature_f:>5.0f} F  "
          f"{step.pressure_psi:>7.0f} psi  {step.density_ppg:>6.2f} ppg")
```

The number that matters:

```python
equivalent_static_density(mud, profile, 20000, step_ft=500)
# 13.81 ppg — not 14.0

pvt_error_psi(mud, profile, 20000, step_ft=500)
# -201 psi
```

**Negative 201 psi.** The simple `0.052 × MW × TVD` calculation **over**-estimates
bottomhole pressure by 201 psi. The real pressure is lower than believed and the
well is closer to flowing than it appears.

That is the dangerous direction, and it is the usual direction for a hot well
with oil-based mud.

The opposite case exists too — a deep, cool well where compression wins:

```python
cool = TemperatureProfile(70, 0.4)
pvt_error_psi(mud, cool, 20000, step_ft=500)    # positive
```

Here the well has *more* overbalance than the kill sheet says, which is safer but
means the fracture gradient is closer than it looks.

## What changes operationally

**Everything is measured, then re-measured.** Slow circulating rates, mud
properties and temperatures all shift as the well heats up. A reading taken this
morning may not be valid this evening.

**Narrow margins.** HPHT wells often have pore pressure and fracture gradient
within a few tenths of a ppg. That drives more casing strings, tighter ECD
management, and frequently [MPD](11-mpd-and-ubd.md).

**Ballooning.** Wellbore breathing — the formation taking mud while circulating
and giving it back when the pumps stop — looks exactly like a kick on the pit
indicators. Distinguishing ballooning from a real influx is a recurring HPHT
problem, and the usual discriminator is that ballooning returns a *finite*
volume that decays, while a kick keeps giving.

**Gas solubility.** In oil-based mud, gas dissolves rather than forming a
discrete bubble. There is no clean influx to identify, shut-in pressures behave
differently, and the gas comes out of solution suddenly and near surface —
where the least warning is available and expansion is most violent.

**Temperature effects on shut-in pressure.** A shut-in HPHT well heats up as
circulation stops and the mud equilibrates with the formation. Surface pressures
can climb for reasons that have nothing to do with gas migration. Distinguishing
thermal pressure rise from migration matters, because the responses differ.

**Equipment rating.** 15,000 psi and 20,000 psi BOP stacks, elastomers rated for
temperature, and MWD tools that survive the heat. Much HPHT difficulty is
equipment availability rather than arithmetic.

## Using it

```python
from wellcontrol.hpht import MudPVT, TemperatureProfile, equivalent_static_density
from wellcontrol.hydrostatics import hydrostatic_pressure

mud = MudPVT.typical(14.5, "synthetic_based")
profile = TemperatureProfile.from_bottomhole(70, 340, 18000)

naive = hydrostatic_pressure(14.5, 18000)
esd = equivalent_static_density(mud, profile, 18000, step_ft=250)

print(f"Naive:     {naive:.0f} psi at {14.5:.2f} ppg")
print(f"Corrected: {0.052 * esd * 18000:.0f} psi at {esd:.2f} ppg ESD")
```

Compare the ESD — not the pit density — against pore pressure and fracture
gradient. That is the whole practical point of this module.

---

Previous: [Subsea wells](09-subsea-wells.md) · Next: [MPD and underbalanced drilling](11-mpd-and-ubd.md)
