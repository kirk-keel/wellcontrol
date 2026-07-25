"""Survey and pipe tally import tests.

Two jobs: check the maths (minimum curvature against geometry that can be
worked by hand), and check that bad files are rejected with a message rather
than silently coerced into something plottable.
"""

from pathlib import Path

import pytest

from wellcontrol.importers import (
    import_survey,
    import_tally,
)
from wellcontrol.survey import Survey

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# --------------------------------------------------------------------------
# Minimum curvature
# --------------------------------------------------------------------------

class TestMinimumCurvature:
    def test_vertical_hole_tvd_equals_md(self):
        survey = Survey.from_minimum_curvature([
            (0.0, 0.0, 0.0), (5000.0, 0.0, 0.0), (10000.0, 0.0, 0.0),
        ])
        assert survey.total_tvd == pytest.approx(10000.0)

    def test_ninety_degree_build_matches_radius_of_curvature(self):
        """Building 0 to 90 degrees over 1000 ft of hole.

        The arc radius is R = 1000 / (pi/2) = 636.6 ft, and the TVD gained is
        R x sin(90) = 636.6 ft. Minimum curvature must agree.
        """
        survey = Survey.from_minimum_curvature([
            (0.0, 0.0, 0.0), (1000.0, 90.0, 0.0),
        ])
        assert survey.total_tvd == pytest.approx(636.6, abs=0.5)

    def test_horizontal_section_gains_no_tvd(self):
        survey = Survey.from_minimum_curvature([
            (0.0, 90.0, 0.0), (5000.0, 90.0, 0.0),
        ])
        assert survey.total_tvd == pytest.approx(0.0, abs=0.1)

    def test_tangent_section_is_simple_trigonometry(self):
        """1000 ft at a constant 60 degrees gains 1000 x cos(60) = 500 ft."""
        survey = Survey.from_minimum_curvature([
            (0.0, 60.0, 0.0), (1000.0, 60.0, 0.0),
        ])
        assert survey.total_tvd == pytest.approx(500.0, abs=0.1)

    def test_ratio_factor_beats_straight_line_through_a_build(self):
        """The arc correction is what straight-line averaging misses."""
        survey = Survey.from_minimum_curvature([
            (0.0, 0.0, 0.0), (1000.0, 90.0, 0.0),
        ])
        straight_line = 1000.0 * (1.0 + 0.0) / 2.0     # average of cosines
        assert survey.total_tvd > straight_line

    def test_northing_follows_the_azimuth(self):
        """Due north at 90 degrees inclination: all the displacement is north."""
        survey = Survey.from_minimum_curvature([
            (0.0, 90.0, 0.0), (1000.0, 90.0, 0.0),
        ])
        assert survey.stations[-1].north_ft == pytest.approx(1000.0, abs=1.0)
        assert survey.stations[-1].east_ft == pytest.approx(0.0, abs=1.0)

    def test_easting_follows_the_azimuth(self):
        survey = Survey.from_minimum_curvature([
            (0.0, 90.0, 90.0), (1000.0, 90.0, 90.0),
        ])
        assert survey.stations[-1].east_ft == pytest.approx(1000.0, abs=1.0)
        assert survey.stations[-1].north_ft == pytest.approx(0.0, abs=1.0)

    def test_dogleg_severity(self):
        """30 degrees of turn over 1000 ft is 3 deg/100 ft."""
        survey = Survey.from_minimum_curvature([
            (0.0, 0.0, 0.0), (1000.0, 30.0, 0.0),
        ])
        assert survey.stations[-1].dogleg_severity == pytest.approx(3.0, abs=0.05)

    def test_straight_hole_has_no_dogleg(self):
        survey = Survey.from_minimum_curvature([
            (0.0, 30.0, 45.0), (1000.0, 30.0, 45.0),
        ])
        assert survey.max_dogleg_severity == pytest.approx(0.0, abs=0.01)

    def test_tie_in_offsets_the_whole_survey(self):
        survey = Survey.from_minimum_curvature(
            [(5000.0, 0.0, 0.0), (6000.0, 0.0, 0.0)], tie_in_tvd_ft=5000.0
        )
        assert survey.total_tvd == pytest.approx(6000.0)

    def test_needs_two_stations(self):
        with pytest.raises(ValueError, match="at least two stations"):
            Survey.from_minimum_curvature([(0.0, 0.0, 0.0)])

    def test_rejects_repeated_depth(self):
        with pytest.raises(ValueError, match="must increase"):
            Survey.from_minimum_curvature([
                (0.0, 0.0, 0.0), (1000.0, 10.0, 0.0), (1000.0, 20.0, 0.0),
            ])


# --------------------------------------------------------------------------
# Survey import
# --------------------------------------------------------------------------

class TestSurveyImport:
    def test_reads_the_sample(self):
        result = import_survey(SAMPLES / "survey_horizontal.csv")
        assert result.survey is not None
        assert result.rows_read == 39
        assert result.survey.total_md == pytest.approx(12000.0)

    def test_sample_reaches_horizontal(self):
        survey = import_survey(SAMPLES / "survey_horizontal.csv").survey
        assert survey.max_inclination_deg == pytest.approx(90.3, abs=0.1)

    def test_sample_tvd_is_plausible(self):
        """Build from 4000 ft at 3 deg/100 ft reaches roughly 5900 ft TVD."""
        survey = import_survey(SAMPLES / "survey_horizontal.csv").survey
        assert survey.total_tvd == pytest.approx(5900.0, abs=60.0)

    def test_lateral_gains_almost_no_tvd(self):
        survey = import_survey(SAMPLES / "survey_horizontal.csv").survey
        assert survey.vertical_height_of(8000.0, 12000.0) == pytest.approx(
            0.0, abs=20.0
        )

    def test_accepts_csv_text_directly(self):
        result = import_survey("MD,Inc,Azi\n0,0,0\n1000,0,0\n2000,0,0\n")
        assert result.survey.total_tvd == pytest.approx(2000.0)

    @pytest.mark.parametrize("header", [
        "MD,Inc,Azi",
        "Measured Depth,Inclination,Azimuth",
        "DEPTH,INCL,AZM",
        "Hole Depth,Drift,Bearing",
        "md,inc,azi",
    ])
    def test_header_spellings(self, header):
        result = import_survey(f"{header}\n0,0,0\n1000,0,0\n")
        assert result.survey is not None

    def test_uses_recorded_tvd_when_present(self):
        result = import_survey(
            "MD,Inc,Azi,TVD\n0,0,0,0\n1000,0,0,1000\n2000,0,0,2000\n"
        )
        assert result.tvd_was_computed is False

    def test_computes_tvd_when_absent(self):
        result = import_survey("MD,Inc,Azi\n0,0,0\n1000,0,0\n")
        assert result.tvd_was_computed is True

    def test_can_be_told_to_ignore_recorded_tvd(self):
        result = import_survey(
            "MD,Inc,Azi,TVD\n0,0,0,0\n1000,0,0,1000\n",
            use_recorded_tvd=False,
        )
        assert result.tvd_was_computed is True

    def test_warns_when_recorded_tvd_disagrees(self):
        """A 60 ft discrepancy over a vertical hole is a datum problem."""
        result = import_survey(
            "MD,Inc,Azi,TVD\n0,0,0,0\n1000,0,0,940\n2000,0,0,1940\n"
        )
        assert any("differs from minimum curvature" in w for w in result.warnings)

    def test_warns_when_azimuth_missing(self):
        result = import_survey("MD,Inc\n0,0\n1000,0\n")
        assert any("azimuth" in w.lower() for w in result.warnings)

    def test_tolerates_units_and_commas(self):
        result = import_survey(
            'MD,Inc,Azi\n"0 ft",0 deg,0\n"1,000 ft",0 deg,0\n'
        )
        assert result.survey.total_md == pytest.approx(1000.0)

    def test_sorts_out_of_order_rows(self):
        result = import_survey("MD,Inc,Azi\n1000,0,0\n0,0,0\n2000,0,0\n")
        assert any("depth order" in w for w in result.warnings)
        assert result.survey.total_md == pytest.approx(2000.0)


class TestSurveyImportRejects:
    def test_missing_depth_column(self):
        with pytest.raises(ValueError, match="measured depth column"):
            import_survey("Inclination,Azimuth\n0,0\n1000,0\n")

    def test_missing_inclination_column(self):
        with pytest.raises(ValueError, match="inclination column"):
            import_survey("MD,Azimuth\n0,0\n1000,0\n")

    def test_empty_file(self):
        with pytest.raises(ValueError, match="empty"):
            import_survey("")

    def test_single_station(self):
        with pytest.raises(ValueError, match="at least two stations"):
            import_survey("MD,Inc,Azi\n0,0,0\n")

    def test_impossible_inclination(self):
        with pytest.raises(ValueError, match="outside 0-180"):
            import_survey("MD,Inc,Azi\n0,0,0\n1000,200,0\n")

    def test_duplicate_depths(self):
        with pytest.raises(ValueError, match="duplicate measured depths"):
            import_survey("MD,Inc,Azi\n0,0,0\n1000,0,0\n1000,5,0\n")

    def test_unreadable_number_names_the_row(self):
        with pytest.raises(ValueError, match="Row 3"):
            import_survey("MD,Inc,Azi\n0,0,0\nabc,0,0\n")

    def test_inconsistent_recorded_tvd(self):
        """TVD cannot gain faster than MD."""
        with pytest.raises(ValueError, match="not physically consistent"):
            import_survey("MD,Inc,Azi,TVD\n0,0,0,0\n1000,0,0,1500\n")


# --------------------------------------------------------------------------
# Tally import
# --------------------------------------------------------------------------

class TestTallyImport:
    def test_reads_the_sample(self):
        result = import_tally(SAMPLES / "pipe_tally.csv")
        assert len(result.components) == 8

    def test_joint_count_multiplies_the_length(self):
        """12 joints at 30.5 ft is 366 ft of collars."""
        result = import_tally(SAMPLES / "pipe_tally.csv")
        collars = next(
            c for c in result.components if c.name.lower() == "drill collars"
        )
        assert collars.length_ft == pytest.approx(366.0)

    def test_total_length(self):
        """4.5 + 28 + 3.2 + 31 + (12 x 30.5) + 31.5 + (15 x 31.2) + (352 x 31.4)
        = 4.5 + 28 + 3.2 + 31 + 366 + 31.5 + 468 + 11052.8 = 11,985.0 ft
        """
        result = import_tally(SAMPLES / "pipe_tally.csv")
        assert result.total_length_ft == pytest.approx(11985.0, abs=0.5)

    def test_everything_fits_a_six_inch_lateral(self):
        """The tally pairs with the sample survey, whose lateral is 6 in."""
        result = import_tally(SAMPLES / "pipe_tally.csv")
        assert max(c.od_in for c in result.components) < 6.0

    def test_bottom_up_by_default(self):
        """First row is the deepest component -- the bit sub."""
        result = import_tally(SAMPLES / "pipe_tally.csv")
        assert "bit" in result.components[0].name.lower()

    def test_top_down_reverses(self):
        result = import_tally(SAMPLES / "pipe_tally.csv", bottom_up=False)
        assert "bit" in result.components[-1].name.lower()

    def test_internal_volume_is_computed(self):
        result = import_tally(SAMPLES / "pipe_tally.csv")
        assert result.internal_volume_bbl > 100.0

    @pytest.mark.parametrize("header", [
        "Description,OD,ID,Length",
        "Name,OD in,ID in,Length ft",
        "Component,Outside Diameter,Inside Diameter,Footage",
        "Item,od,id,len",
    ])
    def test_header_spellings(self, header):
        result = import_tally(f"{header}\nDrill pipe,5.0,4.276,1000\n")
        assert len(result.components) == 1

    def test_names_default_when_absent(self):
        result = import_tally("OD,ID,Length\n5.0,4.276,1000\n6.5,2.8125,600\n")
        assert result.components[0].name == "Component 1"

    def test_warns_when_the_tally_misses_the_bit_depth(self):
        result = import_tally(
            "OD,ID,Length\n5.0,4.276,9000\n",
            expected_bit_depth_ft=10000.0,
        )
        assert any("difference of" in w for w in result.warnings)

    def test_no_warning_when_it_matches(self):
        result = import_tally(
            "OD,ID,Length\n5.0,4.276,10000\n",
            expected_bit_depth_ft=10000.0,
        )
        assert not any("difference of" in w for w in result.warnings)

    def test_warns_on_a_single_component(self):
        result = import_tally("OD,ID,Length\n5.0,4.276,10000\n")
        assert any("only one component" in w for w in result.warnings)


class TestTallyImportRejects:
    def test_missing_od(self):
        with pytest.raises(ValueError, match="outside diameter column"):
            import_tally("ID,Length\n4.276,1000\n")

    def test_missing_length(self):
        with pytest.raises(ValueError, match="length column"):
            import_tally("OD,ID\n5.0,4.276\n")

    def test_id_not_smaller_than_od(self):
        with pytest.raises(ValueError, match="right way round"):
            import_tally("OD,ID,Length\n4.276,5.0,1000\n")

    def test_negative_length(self):
        with pytest.raises(ValueError, match="length must be positive"):
            import_tally("OD,ID,Length\n5.0,4.276,-100\n")

    def test_implausible_diameter(self):
        """Someone has given millimetres."""
        with pytest.raises(ValueError, match="implausible"):
            import_tally("OD,ID,Length\n127,108,1000\n")

    def test_row_number_is_named(self):
        with pytest.raises(ValueError, match="Row 3"):
            import_tally("OD,ID,Length\n5.0,4.276,1000\n5.0,x,1000\n")


# --------------------------------------------------------------------------
# Using imported data
# --------------------------------------------------------------------------

class TestImportedGeometryDrivesTheCalculations:
    def test_imported_survey_gives_a_usable_tvd(self):
        survey = import_survey(SAMPLES / "survey_horizontal.csv").survey
        assert survey.tvd_at(12000.0) < 6100.0
        assert survey.tvd_at(4000.0) == pytest.approx(4000.0, abs=1.0)

    def test_imported_survey_finds_its_sections(self):
        survey = import_survey(SAMPLES / "survey_horizontal.csv").survey
        names = [n for _, _, n in survey.trajectory_sections()]
        assert "Vertical" in names
        assert "Build" in names
        assert "Lateral" in names

    def test_imported_tally_builds_a_drill_string(self):
        from wellcontrol.geometry import DrillString

        result = import_tally(SAMPLES / "pipe_tally.csv")
        bha = result.components[:-1]
        drill_pipe = result.components[-1]
        string = DrillString.from_bha(bha, drill_pipe, 12000.0)
        assert string.bit_depth_md == pytest.approx(12000.0)
        assert string.internal_volume_bbl > 0

    def test_real_tally_volume_differs_from_the_nominal_two_component_string(self):
        """The reason to import one: eight components across two pipe sizes do
        not have the same internal volume as two nominal components, and string
        volume sets the strokes to bit.
        """
        from wellcontrol import examples
        from wellcontrol.geometry import DrillString

        result = import_tally(SAMPLES / "pipe_tally.csv")
        real = DrillString.from_bha(
            result.components[:-1], result.components[-1], 12000.0
        )
        annulus, _ = examples.horizontal_well()
        nominal = annulus.string

        assert abs(real.internal_volume_bbl - nominal.internal_volume_bbl) > 1.0

    def test_sample_tally_and_survey_build_a_valid_annulus(self):
        """The two samples are meant to be used together, so the string must
        physically fit the hole the survey describes.
        """
        from wellcontrol.geometry import (
            Annulus, DrillString, HoleSection, Wellbore,
        )

        components = import_tally(SAMPLES / "pipe_tally.csv").components
        wellbore = Wellbore([
            HoleSection("Casing", id_in=8.681, top_md=0.0, bottom_md=7200.0),
            HoleSection("Lateral", id_in=6.0, top_md=7200.0, bottom_md=12000.0,
                        is_open_hole=True),
        ])
        string = DrillString.from_bha(components[:-1], components[-1], 12000.0)
        annulus = Annulus(wellbore, string)
        assert annulus.volume_bbl > 0


class TestStringMustFitTheHole:
    def test_oversized_pipe_is_rejected_with_a_useful_message(self):
        """Pairing a tally with the wrong hole section is a plausible mistake,
        and it used to surface deep inside a volume calculation.
        """
        from wellcontrol.geometry import (
            Annulus, DrillString, HoleSection, Pipe, Wellbore,
        )

        wellbore = Wellbore([
            HoleSection("Lateral", id_in=6.0, top_md=0.0, bottom_md=10000.0,
                        is_open_hole=True),
        ])
        collars = Pipe("8in Drill Collars", od_in=8.0, id_in=3.0, length_ft=500.0)
        drill_pipe = Pipe("Drill Pipe", od_in=4.0, id_in=3.34, length_ft=0.0)
        string = DrillString.from_bha([collars], drill_pipe, 10000.0)

        with pytest.raises(ValueError, match="does not fit inside"):
            Annulus(wellbore, string)

    def test_message_names_the_component_and_the_section(self):
        from wellcontrol.geometry import (
            Annulus, DrillString, HoleSection, Pipe, Wellbore,
        )

        wellbore = Wellbore([
            HoleSection("6in Lateral", id_in=6.0, top_md=0.0, bottom_md=10000.0,
                        is_open_hole=True),
        ])
        collars = Pipe("8in Drill Collars", od_in=8.0, id_in=3.0, length_ft=500.0)
        drill_pipe = Pipe("Drill Pipe", od_in=4.0, id_in=3.34, length_ft=0.0)
        string = DrillString.from_bha([collars], drill_pipe, 10000.0)

        with pytest.raises(ValueError) as info:
            Annulus(wellbore, string)
        message = str(info.value)
        assert "8in Drill Collars" in message
        assert "6in Lateral" in message
        assert "pipe tally" in message
