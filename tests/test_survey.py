"""Survey and MD/TVD tests -- the distinction that breaks directional kills."""

import pytest

from wellcontrol import examples
from wellcontrol.survey import Survey, SurveyStation


class TestVerticalSurvey:
    def test_md_equals_tvd(self):
        survey = Survey.vertical(10000.0)
        assert survey.tvd_at(5000.0) == pytest.approx(5000.0)
        assert survey.total_tvd == pytest.approx(10000.0)

    def test_md_at_inverts_tvd_at(self):
        survey = Survey.vertical(10000.0)
        assert survey.md_at(3200.0) == pytest.approx(3200.0)


class TestValidation:
    def test_needs_two_stations(self):
        with pytest.raises(ValueError, match="at least two stations"):
            Survey([SurveyStation(0.0, 0.0)])

    def test_tvd_cannot_outrun_md(self):
        with pytest.raises(ValueError, match="exceeds MD gain"):
            Survey([
                SurveyStation(0.0, 0.0),
                SurveyStation(1000.0, 1500.0),
            ])

    def test_tvd_cannot_decrease(self):
        with pytest.raises(ValueError, match="drilled upward"):
            Survey([
                SurveyStation(0.0, 0.0),
                SurveyStation(1000.0, 1000.0),
                SurveyStation(2000.0, 900.0),
            ])

    def test_out_of_range_md_is_rejected(self):
        survey = Survey.vertical(10000.0)
        with pytest.raises(ValueError, match="outside the surveyed interval"):
            survey.tvd_at(12000.0)


class TestBuildAndHold:
    def test_horizontal_well_tvd(self):
        """KOP 4000, 3 deg/100ft, build to 90 deg.

        Build length = 90 / 3 x 100 = 3000 ft, so end of build at 7000 ft MD.
        Radius = (180/pi) x (100/3) = 1909.859 ft.
        TVD at end of build = 4000 + 1909.859 x sin(90) = 5909.859 ft.
        The lateral adds MD but no TVD.
        """
        survey = examples.horizontal_survey()
        assert survey.tvd_at(7000.0) == pytest.approx(5909.859, abs=0.1)
        assert survey.tvd_at(12000.0) == pytest.approx(5909.859, abs=0.1)
        assert survey.total_md == pytest.approx(12000.0)

    def test_vertical_section_above_kop(self):
        survey = examples.horizontal_survey()
        assert survey.tvd_at(2000.0) == pytest.approx(2000.0, abs=0.01)
        assert survey.tvd_at(4000.0) == pytest.approx(4000.0, abs=0.01)

    def test_45_degrees_through_the_build(self):
        """At 45 deg the build has run 1500 ft MD, and
        TVD = 4000 + 1909.859 x sin(45) = 4000 + 1350.4 = 5350.4 ft.
        """
        survey = examples.horizontal_survey()
        assert survey.tvd_at(5500.0) == pytest.approx(5350.4, abs=1.0)

    def test_inclination_builds_then_holds(self):
        survey = examples.horizontal_survey()
        assert survey.inclination_at(2000.0) == pytest.approx(0.0, abs=0.1)
        assert survey.inclination_at(5500.0) == pytest.approx(45.0, abs=0.5)
        assert survey.inclination_at(10000.0) == pytest.approx(90.0, abs=0.1)

    def test_total_md_shallower_than_build_is_rejected(self):
        with pytest.raises(ValueError, match="shallower than the end of the build"):
            Survey.build_and_hold(
                kop_md=4000.0,
                build_rate_deg_per_100ft=3.0,
                final_inclination_deg=90.0,
                total_md=5000.0,
            )

    def test_negative_build_rate_is_rejected(self):
        with pytest.raises(ValueError, match="Build rate must be positive"):
            Survey.build_and_hold(4000.0, -3.0, 90.0, 12000.0)


class TestVerticalHeight:
    def test_lateral_has_no_vertical_height(self):
        """A 1000 ft slug of influx in the lateral generates no hydrostatic and
        cannot migrate.
        """
        survey = examples.horizontal_survey()
        assert survey.vertical_height_of(11000.0, 12000.0) == pytest.approx(
            0.0, abs=0.5
        )

    def test_vertical_section_height_equals_length(self):
        survey = examples.horizontal_survey()
        assert survey.vertical_height_of(1000.0, 3000.0) == pytest.approx(
            2000.0, abs=0.01
        )

    def test_argument_order_does_not_matter(self):
        survey = examples.horizontal_survey()
        assert survey.vertical_height_of(3000.0, 1000.0) == pytest.approx(
            survey.vertical_height_of(1000.0, 3000.0)
        )


class TestMdAtTvd:
    def test_returns_shallowest_md_in_a_lateral(self):
        """Many measured depths share the lateral's TVD; the shallowest is the
        useful answer for locating a shoe or a formation top.
        """
        survey = examples.horizontal_survey()
        md = survey.md_at(5909.0)
        assert md < 7000.0

    def test_round_trip_in_the_build(self):
        survey = examples.horizontal_survey()
        tvd = survey.tvd_at(5500.0)
        assert survey.md_at(tvd) == pytest.approx(5500.0, abs=5.0)
