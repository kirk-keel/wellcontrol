"""Import real directional surveys and pipe tallies.

The generated geometry elsewhere in this package is idealised: a build-and-hold
trajectory and a two-component string. Real wells are neither. A survey has
stations at irregular spacing with real doglegs, and a string is a tally of
however many components were actually run.

Importing the real thing is what turns a planning figure into one you would act
on. It matters most where the idealisation is furthest from the truth:

* **TVD through a build.** A generated trajectory assumes a constant build
  rate; a real one wanders. Kill mud weight comes straight off TVD.
* **String volume.** A tally of eleven components with three pipe sizes has a
  different internal volume, and therefore different strokes to bit, than two
  nominal components.

## What these functions do not do

They do not guess. A file whose columns cannot be identified, whose depths run
backwards, or whose numbers are out by a factor of a thousand is rejected with
a message naming the row -- not silently coerced into something plottable. A
well control calculation built on a misread file is worse than no calculation,
because it looks authoritative.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path

from .geometry import Pipe
from .survey import Survey, SurveyStation

# --------------------------------------------------------------------------
# Header matching
# --------------------------------------------------------------------------

#: Header spellings seen in real survey exports, normalised to a canonical key.
SURVEY_ALIASES: dict[str, tuple[str, ...]] = {
    "md": (
        "md", "measureddepth", "measured depth", "depth", "meas depth",
        "mddepth", "holedepth", "hole depth", "dept", "measdepth",
    ),
    "inclination": (
        "inc", "incl", "inclination", "angle", "drift", "inclinationdeg",
        "inc deg", "incdeg", "dip",
    ),
    "azimuth": (
        "azi", "azm", "azimuth", "azimuthdeg", "azi deg", "azideg", "bearing",
        "direction", "hazi", "azimuthgrid",
    ),
    "tvd": (
        "tvd", "truevertdepth", "true vertical depth", "verticaldepth",
        "tvdss", "tvddepth",
    ),
}

#: Columns that carry a running total rather than a per-row value. Used to
#: cross-check the import; a tally that disagrees with its own cumulative
#: column has been read wrongly.
CUMULATIVE_ALIASES: tuple[str, ...] = (
    "cumlength", "cumlengthft", "cumulativelength", "runninglength",
    "bottomdepth", "bottomdepthft", "depthout",
)

#: Header spellings seen in real pipe tallies.
TALLY_ALIASES: dict[str, tuple[str, ...]] = {
    "name": (
        "name", "description", "desc", "component", "item", "type",
        "tool", "detail", "tubular",
    ),
    "od": ("od", "odin", "od in", "outsidediameter", "outside diameter"),
    "id": ("id", "idin", "id in", "insidediameter", "inside diameter", "bore"),
    "length": (
        "length", "lengthft", "length ft", "len", "totallength",
        "total length", "footage", "cumlength",
    ),
    # Deliberately narrow. "no" and "num" were here once and substring-matched
    # "Item_No", so every component's length was multiplied by its row number
    # -- a real tally imported as 2.5 million feet with only a soft warning.
    # A count column is worth having but not worth guessing at.
    "count": ("count", "joints", "jts", "qty", "quantity", "pieces"),
    "weight": (
        "weight", "weightlbft", "lb/ft", "lbft", "nominalweight", "ppf",
    ),
}


def _normalise(header: str) -> str:
    """Reduce a header to letters and digits, lowercased."""
    return "".join(c for c in header.lower() if c.isalnum() or c == " ").strip()


def _tokens(header: str) -> list[str]:
    """Split a header into words on separators and case changes.

    ``MD_ft`` becomes ``["md", "ft"]`` and ``Item_No`` becomes
    ``["item", "no"]``. Matching on whole tokens is what lets a two-letter
    alias like ``md`` or ``od`` be used safely: it matches ``MD_ft`` but not
    ``wood``, because ``wood`` is a single token.
    """
    out: list[str] = []
    current = ""
    for character in header:
        if character.isalnum():
            current += character.lower()
        elif current:
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return out


def _resolve_columns(
    headers: list[str], aliases: dict[str, tuple[str, ...]],
    avoid: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, str]:
    """Map canonical names onto the file's actual headers.

    Three passes, narrowing in confidence:

    1. The whole header matches an alias exactly.
    2. One of the header's **tokens** matches an alias. ``MD_ft`` matches
       ``md`` here; ``wood`` does not match ``od``, because token matching
       respects word boundaries where substring matching does not.
    3. The header *contains* an alias, for aliases long enough to be
       unambiguous. This is the loosest pass and the one that caused a real
       misread, so short aliases are excluded from it.

    Args:
        avoid: Normalised header forms a given canonical must not match --
            used to stop a cumulative column being taken as a per-row one.
    """
    found: dict[str, str] = {}
    normalised = {h: _normalise(h) for h in headers}
    tokenised = {h: _tokens(h) for h in headers}
    avoid = avoid or {}

    def blocked(canonical: str, header: str) -> bool:
        compact = normalised[header].replace(" ", "")
        return compact in avoid.get(canonical, ())

    for canonical, options in aliases.items():
        for header, plain in normalised.items():
            if blocked(canonical, header):
                continue
            if plain in options or plain.replace(" ", "") in options:
                found[canonical] = header
                break

    for canonical, options in aliases.items():
        if canonical in found:
            continue
        for header in headers:
            if header in found.values() or blocked(canonical, header):
                continue
            if any(token in options for token in tokenised[header]):
                found[canonical] = header
                break

    for canonical, options in aliases.items():
        if canonical in found:
            continue
        for header, plain in normalised.items():
            if header in found.values() or blocked(canonical, header):
                continue
            compact = plain.replace(" ", "")
            if any(
                len(o) >= 4 and o.replace(" ", "") in compact for o in options
            ):
                found[canonical] = header
                break

    return found


def _looks_like_a_row_index(values: list[float]) -> bool:
    """True when a column is just numbering the rows.

    A count column and an index column are easy to confuse -- both are small
    integers in the first rows. An index counts 1, 2, 3 with every row; a
    genuine count repeats and jumps. Treating an index as a count multiplies
    every length by its position, so it is worth detecting explicitly.
    """
    if len(values) < 3:
        return False
    steps = [b - a for a, b in zip(values, values[1:])]
    return all(abs(step - 1.0) < 1e-9 for step in steps)


def _to_float(value: object, row: int, column: str) -> float:
    """Parse a number, tolerating commas, units and blanks."""
    if value is None:
        raise ValueError(f"Row {row}: '{column}' is empty.")
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError(f"Row {row}: '{column}' is empty.")
    # Strip a trailing unit, e.g. "8500 ft" or "12.25in".
    cleaned = []
    for character in text:
        if character.isdigit() or character in ".-+eE":
            cleaned.append(character)
        else:
            break
    try:
        return float("".join(cleaned))
    except ValueError as exc:
        raise ValueError(
            f"Row {row}: could not read '{value}' in column '{column}' as a "
            "number."
        ) from exc


def _read_rows(source: str | Path | io.StringIO) -> list[dict[str, str]]:
    """Read CSV from a path, a string of CSV text, or an open text buffer."""
    if isinstance(source, io.StringIO):
        text = source.getvalue()
    elif isinstance(source, Path):
        text = source.read_text(encoding="utf-8-sig")
    elif not str(source).strip():
        raise ValueError("The file appears to be empty.")
    elif "\n" in str(source) or "," in str(source):
        text = str(source)
    else:
        text = Path(source).read_text(encoding="utf-8-sig")

    text = text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("The file appears to be empty.")
    return [row for row in reader if any((v or "").strip() for v in row.values())]


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass
class ImportResult:
    """What an import produced, and anything the reader should know.

    ``warnings`` are things that parsed but look odd -- a big dogleg, a tally
    that does not reach the bit. They do not stop the import; they are surfaced
    so a person can judge.
    """

    warnings: list[str] = field(default_factory=list)
    rows_read: int = 0
    columns_used: dict[str, str] = field(default_factory=dict)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class SurveyImport(ImportResult):
    survey: Survey | None = None
    tvd_was_computed: bool = True


@dataclass
class TallyImport(ImportResult):
    components: list[Pipe] = field(default_factory=list)

    @property
    def total_length_ft(self) -> float:
        return sum(c.length_ft for c in self.components)

    @property
    def internal_volume_bbl(self) -> float:
        return sum(c.volume_bbl for c in self.components)


# --------------------------------------------------------------------------
# Survey
# --------------------------------------------------------------------------

def import_survey(
    source: str | Path | io.StringIO,
    *,
    use_recorded_tvd: bool = True,
    max_dogleg_warning: float = 10.0,
) -> SurveyImport:
    """Read a directional survey from CSV.

    Needs measured depth and inclination as a minimum. Azimuth is used when
    present and assumed constant at zero when not -- which is harmless for TVD
    in a single-plane well and wrong for northing and easting, so it warns.

    TVD is computed by minimum curvature. If the file carries its own TVD
    column it is used instead when ``use_recorded_tvd`` is set, because the
    surveyor's TVD is authoritative and may include corrections this
    calculation does not model.

    Args:
        source: A path, a string of CSV text, or an open text buffer.
        use_recorded_tvd: Prefer a TVD column in the file over computing it.
        max_dogleg_warning: Warn above this dogleg severity, deg/100 ft.

    Raises:
        ValueError: with a message naming the row or column at fault.
    """
    rows = _read_rows(source)
    if not rows:
        raise ValueError("No data rows found in the survey file.")

    columns = _resolve_columns(list(rows[0].keys()), SURVEY_ALIASES)
    result = SurveyImport(rows_read=len(rows), columns_used=dict(columns))

    if "md" not in columns:
        raise ValueError(
            "Could not find a measured depth column. Expected a header like "
            f"'MD', 'Measured Depth' or 'Depth'; found: "
            f"{', '.join(rows[0].keys())}"
        )
    if "inclination" not in columns:
        raise ValueError(
            "Could not find an inclination column. Expected a header like "
            f"'Inc', 'Incl' or 'Inclination'; found: "
            f"{', '.join(rows[0].keys())}"
        )

    has_azimuth = "azimuth" in columns
    if not has_azimuth:
        result.warn(
            "No azimuth column found, so azimuth is taken as zero throughout. "
            "True vertical depth is unaffected in a single-plane well, but "
            "northing and easting will be wrong."
        )

    raw: list[tuple[float, float, float]] = []
    recorded_tvd: list[float] = []
    for index, row in enumerate(rows, start=2):   # row 1 is the header
        md = _to_float(row[columns["md"]], index, "measured depth")
        inclination = _to_float(row[columns["inclination"]], index, "inclination")
        azimuth = (
            _to_float(row[columns["azimuth"]], index, "azimuth")
            if has_azimuth else 0.0
        )

        if not 0.0 <= inclination <= 180.0:
            raise ValueError(
                f"Row {index}: inclination {inclination} is outside 0-180 "
                "degrees. Check the column has not been read as something else."
            )
        if not -360.0 <= azimuth <= 360.0:
            raise ValueError(
                f"Row {index}: azimuth {azimuth} is outside -360 to 360 degrees."
            )

        raw.append((md, inclination, azimuth % 360.0))
        if "tvd" in columns:
            try:
                recorded_tvd.append(_to_float(row[columns["tvd"]], index, "tvd"))
            except ValueError:
                recorded_tvd.append(math.nan)

    if len(raw) < 2:
        raise ValueError(
            f"A survey needs at least two stations; the file has {len(raw)}."
        )

    depths = [md for md, _, _ in raw]
    if len(set(depths)) != len(depths):
        raise ValueError(
            "The survey has duplicate measured depths. Remove the repeated "
            "stations before importing."
        )
    if depths != sorted(depths):
        result.warn(
            "The survey rows were not in depth order and have been sorted."
        )

    survey = Survey.from_minimum_curvature(raw)

    use_file_tvd = (
        use_recorded_tvd
        and "tvd" in columns
        and len(recorded_tvd) == len(raw)
        and not any(math.isnan(v) for v in recorded_tvd)
    )
    if use_file_tvd:
        ordered = sorted(zip(raw, recorded_tvd), key=lambda pair: pair[0][0])
        stations = [
            SurveyStation(
                md=md,
                tvd=tvd,
                inclination_deg=inc,
                azimuth_deg=azi,
                north_ft=computed.north_ft,
                east_ft=computed.east_ft,
                dogleg_severity=computed.dogleg_severity,
            )
            for ((md, inc, azi), tvd), computed in zip(ordered, survey.stations)
        ]
        try:
            survey = Survey(stations)
        except ValueError as exc:
            raise ValueError(
                f"The TVD column in the file is not physically consistent with "
                f"the measured depths: {exc}"
            ) from exc
        result.tvd_was_computed = False

        difference = max(
            abs(a.tvd - b.tvd)
            for a, b in zip(stations, Survey.from_minimum_curvature(raw).stations)
        )
        if difference > 5.0:
            result.warn(
                f"The TVD in the file differs from minimum curvature by up to "
                f"{difference:.0f} ft. The file's values have been used. A large "
                "difference usually means a different tie-in or a datum shift."
            )
    else:
        result.tvd_was_computed = True

    worst = survey.max_dogleg_severity
    if worst > max_dogleg_warning:
        result.warn(
            f"Maximum dogleg severity is {worst:.1f} deg/100 ft. Above about "
            f"{max_dogleg_warning:.0f} that is usually a bad station or a units "
            "problem rather than real curvature -- check the survey."
        )

    result.survey = survey
    return result


# --------------------------------------------------------------------------
# Pipe tally
# --------------------------------------------------------------------------

def _cross_check_against_cumulative(
    rows: list[dict[str, str]], result: "TallyImport"
) -> None:
    """Check the summed lengths against the file's own running total.

    Most real tallies carry a cumulative length or a bottom depth. When they
    do, the file is stating what it should add up to, and a large disagreement
    means the import has misread something -- a count column that was really an
    index, a length column that was really a cumulative one, footer rows picked
    up as data.

    Treated as an **error, not a warning**. A tally that disagrees with itself
    by a factor is not a judgement call.

    Raises:
        ValueError: when the totals differ by more than 2%.
    """
    if not rows:
        return
    normalised = {h: _normalise(h).replace(" ", "") for h in rows[0]}
    header = next(
        (h for h, plain in normalised.items() if plain in CUMULATIVE_ALIASES),
        None,
    )
    if header is None:
        return

    stated = None
    for row in reversed(rows):
        text = (row.get(header) or "").strip().replace(",", "")
        if text:
            try:
                stated = float(text)
            except ValueError:
                continue
            break
    if stated is None or stated <= 0:
        return

    total = result.total_length_ft
    result.columns_used["cumulative check"] = header
    if abs(total - stated) > 0.02 * stated:
        raise ValueError(
            f"The lengths add up to {total:,.1f} ft, but the file's own "
            f"'{header}' column ends at {stated:,.1f} ft. The import has "
            "misread something -- most often a column that numbers the rows "
            "being taken as a joint count, or a cumulative length being taken "
            "as a per-row length. Check the column headings."
        )


def import_tally(
    source: str | Path | io.StringIO,
    *,
    bottom_up: bool = True,
    expected_bit_depth_ft: float | None = None,
) -> TallyImport:
    """Read a pipe tally from CSV.

    Needs outside diameter, inside diameter and length. A ``count`` or
    ``joints`` column multiplies the length, so a tally can list "90 joints at
    31.5 ft" rather than a total.

    Args:
        source: A path, a string of CSV text, or an open text buffer.
        bottom_up: True when the first row is the deepest component, which is
            how a tally is usually written -- bit sub first. Set False for a
            tally written from surface down.
        expected_bit_depth_ft: Warn if the tally does not add up to this.

    Raises:
        ValueError: with a message naming the row or column at fault.
    """
    rows = _read_rows(source)
    if not rows:
        raise ValueError("No data rows found in the tally file.")

    # A cumulative column must never be taken as the per-row length.
    columns = _resolve_columns(
        list(rows[0].keys()), TALLY_ALIASES,
        avoid={"length": CUMULATIVE_ALIASES},
    )
    result = TallyImport(rows_read=len(rows), columns_used=dict(columns))

    for required, description in (
        ("od", "outside diameter"),
        ("id", "inside diameter"),
        ("length", "length"),
    ):
        if required not in columns:
            raise ValueError(
                f"Could not find the {description} column. Found: "
                f"{', '.join(rows[0].keys())}"
            )

    # A count column that is really a row index would multiply every length by
    # its position. Check before trusting it.
    use_count = "count" in columns
    if use_count:
        raw = []
        for row in rows:
            text = (row.get(columns["count"]) or "").strip()
            if text:
                try:
                    raw.append(float(text.replace(",", "")))
                except ValueError:
                    raw = []
                    break
        if _looks_like_a_row_index(raw):
            use_count = False
            result.warn(
                f"Column '{columns['count']}' counts 1, 2, 3 with every row, so "
                "it is numbering the rows rather than counting joints. It has "
                "been ignored. Multiplying each length by it would have been a "
                "large and silent error."
            )
            result.columns_used.pop("count", None)

    components: list[Pipe] = []
    for index, row in enumerate(rows, start=2):
        od = _to_float(row[columns["od"]], index, "outside diameter")
        bore = _to_float(row[columns["id"]], index, "inside diameter")
        length = _to_float(row[columns["length"]], index, "length")

        if use_count:
            raw_count = (row.get(columns["count"]) or "").strip()
            if raw_count:
                count = _to_float(raw_count, index, "count")
                if count > 0:
                    length *= count

        if bore >= od:
            raise ValueError(
                f"Row {index}: inside diameter {bore} is not smaller than "
                f"outside diameter {od}. Check the columns are the right way "
                "round."
            )
        if length <= 0:
            raise ValueError(f"Row {index}: length must be positive, got {length}.")
        if od > 30.0:
            raise ValueError(
                f"Row {index}: outside diameter {od} in is implausible. "
                "Diameters are expected in inches."
            )

        name = (
            (row.get(columns["name"]) or "").strip()
            if "name" in columns else ""
        ) or f"Component {index - 1}"

        components.append(
            Pipe(name=name, od_in=od, id_in=bore, length_ft=length)
        )

    if not bottom_up:
        components.reverse()

    result.components = components
    _cross_check_against_cumulative(rows, result)

    if expected_bit_depth_ft is not None:
        total = result.total_length_ft
        gap = expected_bit_depth_ft - total
        if abs(gap) > 1.0:
            result.warn(
                f"The tally totals {total:,.1f} ft but the bit is at "
                f"{expected_bit_depth_ft:,.1f} ft, a difference of "
                f"{gap:+,.1f} ft. The shallowest component will be stretched or "
                "trimmed to reach the bit."
            )

    if len(components) == 1:
        result.warn(
            "The tally has only one component. That is unusual for a real "
            "string -- check the file has not lost rows."
        )

    return result
