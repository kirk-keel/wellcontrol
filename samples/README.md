# Sample import files

Two files showing the formats the app accepts. Both are CSV; the app also reads
`.xlsx` via pandas.

## `survey_horizontal.csv` — directional survey

```
MD,Inc,Azi
0,0.00,0
500,0.00,0
...
7000,90.00,182
12000,89.90,184
```

**Required:** measured depth and inclination.
**Optional:** azimuth, and TVD.

Headers are matched loosely, so all of these work:

| Quantity | Accepted headers |
| --- | --- |
| Measured depth | `MD`, `Measured Depth`, `Depth`, `Hole Depth`, `Meas Depth` |
| Inclination | `Inc`, `Incl`, `Inclination`, `Angle`, `Drift`, `Dip` |
| Azimuth | `Azi`, `Azm`, `Azimuth`, `Bearing`, `Direction` |
| TVD | `TVD`, `True Vertical Depth`, `TVDSS` |

**TVD is computed by minimum curvature** unless the file supplies its own — in
which case the file's values win, because the surveyor's TVD is authoritative
and may carry corrections this calculation does not model. If the two disagree
by more than 5 ft, the import says so.

Without an azimuth column, azimuth is taken as zero. TVD is unaffected in a
single-plane well; northing and easting will be wrong, and the import warns.

This sample builds from 4,000 ft at 3°/100 ft to horizontal at 7,000 ft, then
runs a 5,000 ft lateral with realistic wander — the inclination is not exactly
90° from station to station, which is what a real survey looks like.

## `pipe_tally.csv` — drill string

```
Description,OD,ID,Length,Joints
Bit and bit sub,4.75,2.2500,4.5,1
Drill collars,4.75,2.2500,30.5,12
Drill pipe 4in 14.0,4.00,3.3400,31.4,352
```

**Required:** OD, ID, length.
**Optional:** description, joint count, weight.

| Quantity | Accepted headers |
| --- | --- |
| Description | `Description`, `Name`, `Component`, `Item`, `Type`, `Tool` |
| OD | `OD`, `OD in`, `Outside Diameter` |
| ID | `ID`, `ID in`, `Inside Diameter`, `Bore` |
| Length | `Length`, `Length ft`, `Len`, `Footage` |
| Count | `Joints`, `Jts`, `Count`, `Qty`, `Pieces` |

**A count column multiplies the length**, so "12 joints at 30.5 ft" gives
366 ft. That is how tallies are usually written.

**Order is bottom-up by default** — the first row is the deepest component, the
bit sub. The app has a toggle for tallies written from surface down.

**The two samples go together.** Everything in the tally is under 6 in OD so it
fits the 6 in lateral the survey describes. Pairing a tally with the wrong hole
section is rejected with a message naming the component and the section — an
8 in collar will not go in a 6 in hole, and the calculation should say so
rather than producing a negative annular volume.

The tally totals 11,985 ft against a 12,000 ft bit, so the import warns about
the 15 ft gap and the drill pipe is stretched to reach bottom. Real tallies
rarely land exactly on the bit depth.

## Why import rather than use the generated geometry

The built-in geometry is idealised: a constant build rate and a two-component
string. Real wells are neither, and two figures are sensitive to the
difference:

- **Kill mud weight** comes straight off TVD, and a generated trajectory does
  not have the real one's wander.
- **Strokes to bit** comes off string volume. This sample tally has eight
  components across three pipe sizes; a two-component approximation gets the
  volume, and therefore the schedule, wrong.

## What gets rejected

Files are not guessed at. These raise an error naming the row:

- Columns that cannot be identified
- Inclination outside 0–180° or azimuth outside ±360°
- Duplicate measured depths
- ID greater than or equal to OD
- Diameters above 30 in, which means the units are not inches
- A TVD column that is not physically consistent with the measured depths
