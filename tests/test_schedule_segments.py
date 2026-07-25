"""Schedule segmentation, shoe pressure metrics, and the strip-then-kill sequence.

The schedule is only a straight line within a section. It changes slope where
the TVD gained per foot changes (the build) and where the volume per foot
changes (a pipe size change). These tests pin that behaviour down, including
the case that matters most: in a lateral the schedule reverses, and drill pipe
pressure has to be taken UP.
"""

import pytest

from wellcontrol import examples
from wellcontrol.methods import plan_kill, strip_then_kill
from wellcontrol.wellconfig import BOPLocation, Trajectory, WellConfiguration

SV = WellConfiguration(BOPLocation.SURFACE, Trajectory.VERTICAL)
SH = WellConfiguration(BOPLocation.SURFACE, Trajectory.HORIZONTAL)
SSV = WellConfiguration(BOPLocation.SUBSEA, Trajectory.VERTICAL)
SSH = WellConfiguration(BOPLocation.SUBSEA, Trajectory.HORIZONTAL)
CONFIGS = WellConfiguration.standard()
CONFIG_IDS = [c.key for c in CONFIGS]


# --------------------------------------------------------------------------
# Trajectory sections
# --------------------------------------------------------------------------

class TestTrajectorySections:
    def test_vertical_well_is_one_section(self):
        well = examples.well_state(SV)
        sections = well.survey.trajectory_sections()
        assert len(sections) == 1
        assert sections[0][2] == "Vertical"

    def test_horizontal_well_has_three(self):
        well = examples.well_state(SH)
        names = [name for _, _, name in well.survey.trajectory_sections()]
        assert names == ["Vertical", "Build", "Lateral"]

    def test_boundaries_match_the_trajectory(self):
        """KOP at 4,000 ft, build finishes at 7,000 ft."""
        well = examples.well_state(SH)
        sections = well.survey.trajectory_sections()
        assert sections[0][1] == pytest.approx(4000.0, abs=100.0)
        assert sections[1][1] == pytest.approx(7000.0, abs=100.0)

    def test_section_at_depth(self):
        well = examples.well_state(SH)
        assert well.survey.section_at(2000.0) == "Vertical"
        assert well.survey.section_at(5500.0) == "Build"
        assert well.survey.section_at(10000.0) == "Lateral"

    def test_sections_are_contiguous_and_cover_the_well(self):
        for config in CONFIGS:
            well = examples.well_state(config)
            sections = well.survey.trajectory_sections()
            assert sections[0][0] == pytest.approx(0.0)
            assert sections[-1][1] == pytest.approx(well.hole_md_ft)
            for upper, lower in zip(sections, sections[1:]):
                assert upper[1] == pytest.approx(lower[0])


# --------------------------------------------------------------------------
# String size changes
# --------------------------------------------------------------------------

class TestSizeChanges:
    def test_collar_top_is_a_size_change(self):
        """600 ft of collars above a 10,000 ft bit puts the change at 9,400."""
        well = examples.well_state(SV)
        assert well.annulus.string.size_change_depths() == pytest.approx([9400.0])

    def test_volume_to_depth_is_the_inverse_of_depth_from_volume(self):
        well = examples.well_state(SV)
        string = well.annulus.string
        for md in (1000.0, 5000.0, 9400.0, 10000.0):
            volume = string.internal_volume_to(md)
            assert well.kill_sheet.kill_mud_depth_at_volume(volume) == (
                pytest.approx(md, abs=1.0)
            )

    def test_volume_to_bit_is_the_whole_string(self):
        well = examples.well_state(SV)
        string = well.annulus.string
        assert string.internal_volume_to(well.bit_md_ft) == pytest.approx(
            string.internal_volume_bbl
        )


# --------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------

class TestScheduleSegments:
    def test_vertical_well_splits_only_at_the_collars(self):
        segments = examples.well_state(SV).kill_sheet.schedule_segments()
        assert len(segments) == 2
        assert segments[0].bottom_md == pytest.approx(9400.0)

    def test_horizontal_well_splits_at_trajectory_and_pipe_changes(self):
        """Vertical, build, lateral, and again at the collars."""
        segments = examples.well_state(SH).kill_sheet.schedule_segments()
        names = [s.name for s in segments]
        assert names == ["Vertical", "Build", "Lateral", "Lateral"]
        assert segments[0].bottom_md == pytest.approx(4000.0, abs=100.0)
        assert segments[1].bottom_md == pytest.approx(7000.0, abs=100.0)
        assert segments[2].bottom_md == pytest.approx(11600.0, abs=1.0)

    def test_segments_are_contiguous_from_surface_to_bit(self):
        for config in CONFIGS:
            well = examples.well_state(config)
            segments = well.kill_sheet.schedule_segments()
            assert segments[0].top_md == pytest.approx(0.0)
            assert segments[-1].bottom_md == pytest.approx(well.bit_md_ft)
            for upper, lower in zip(segments, segments[1:]):
                assert upper.bottom_md == pytest.approx(lower.top_md)

    def test_endpoints_match_icp_and_fcp(self):
        for config in CONFIGS:
            sheet = examples.well_state(config).kill_sheet
            segments = sheet.schedule_segments()
            assert segments[0].start_pressure_psi == pytest.approx(
                sheet.initial_circulating_pressure_psi, abs=1.0
            )
            # Ends below FCP by the overbalance the rounded-up kill weight
            # carries -- the segments hold BHP exactly at formation pressure.
            assert segments[-1].end_pressure_psi == pytest.approx(
                sheet.final_circulating_pressure_psi
                - sheet.rounding_overbalance_psi,
                abs=1.0,
            )

    def test_segments_agree_with_the_step_schedule(self):
        """Both are built from drill_pipe_pressure_at, so they must agree."""
        sheet = examples.well_state(SH).kill_sheet
        for segment in sheet.schedule_segments():
            assert sheet.drill_pipe_pressure_at(segment.top_md) == pytest.approx(
                segment.start_pressure_psi, abs=0.01
            )

    def test_slope_is_constant_through_the_vertical_section(self):
        """No TVD or capacity change, so the schedule is a straight line."""
        sheet = examples.well_state(SH).kill_sheet
        vertical = sheet.schedule_segments()[0]
        midpoint = (vertical.top_md + vertical.bottom_md) / 2.0
        expected = (
            vertical.start_pressure_psi
            + (vertical.end_pressure_psi - vertical.start_pressure_psi) / 2.0
        )
        assert sheet.drill_pipe_pressure_at(midpoint) == pytest.approx(
            expected, abs=1.0
        )

    def test_slope_shallows_through_the_build(self):
        segments = examples.well_state(SH).kill_sheet.schedule_segments()
        vertical, build = segments[0], segments[1]
        assert build.slope_psi_per_100_strokes < (
            vertical.slope_psi_per_100_strokes
        )


class TestLateralReversesTheSchedule:
    """The finding that makes segmentation necessary rather than cosmetic."""

    def test_pressure_rises_in_the_lateral(self):
        segments = examples.well_state(SH).kill_sheet.schedule_segments()
        laterals = [s for s in segments if s.name == "Lateral"]
        assert laterals
        assert all(s.pressure_rises for s in laterals)

    def test_pressure_falls_everywhere_else(self):
        segments = examples.well_state(SH).kill_sheet.schedule_segments()
        for segment in segments:
            if segment.name != "Lateral":
                assert not segment.pressure_rises

    def test_slope_sign_flips(self):
        segments = examples.well_state(SH).kill_sheet.schedule_segments()
        assert segments[0].slope_psi_per_100_strokes > 0     # taking down
        assert segments[-1].slope_psi_per_100_strokes < 0    # taking up

    def test_vertical_well_never_reverses(self):
        segments = examples.well_state(SV).kill_sheet.schedule_segments()
        assert not any(s.pressure_rises for s in segments)

    def test_subsea_horizontal_reverses_too(self):
        segments = examples.well_state(SSH).kill_sheet.schedule_segments()
        assert any(s.pressure_rises for s in segments)

    def test_format_segments_flags_the_direction(self):
        text = examples.well_state(SH).kill_sheet.format_segments()
        assert "UP" in text
        assert "down" in text


# --------------------------------------------------------------------------
# Shoe pressure metrics
# --------------------------------------------------------------------------

class TestShoeMetrics:
    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    def test_shut_in_is_identical_for_every_method(self, config):
        """It is a property of the well, not of what you do about it."""
        well = examples.well_state(config)
        values = {
            plan_kill(well, key).shut_in_shoe_pressure_psi
            for key in ("drillers", "wait_and_weight")
        }
        assert len(values) == 1

    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    def test_overall_peak_is_at_least_both_parts(self, config):
        well = examples.well_state(config)
        plan = plan_kill(well, "wait_and_weight")
        assert plan.peak_shoe_pressure_psi >= plan.shut_in_shoe_pressure_psi
        assert plan.peak_shoe_pressure_psi >= (
            plan.peak_circulating_shoe_pressure_psi
        )

    def test_circulating_peak_discriminates_where_overall_does_not(self):
        """On the vertical well both methods peak at the same shut-in value,
        which hides that Wait and Weight is lower while circulating.
        """
        well = examples.well_state(SV)
        drillers = plan_kill(well, "drillers")
        wait = plan_kill(well, "wait_and_weight")

        assert drillers.peak_shoe_pressure_psi == pytest.approx(
            wait.peak_shoe_pressure_psi
        )
        assert wait.peak_circulating_shoe_pressure_psi < (
            drillers.peak_circulating_shoe_pressure_psi
        )

    def test_summary_reports_the_worst_moment(self):
        summary = plan_kill(examples.well_state(SV), "drillers").summary
        assert summary["Worst moment"] == "shut-in, before pumping"
        assert "Shoe at shut-in (psi)" in summary
        assert "Peak shoe while circulating (psi)" in summary


# --------------------------------------------------------------------------
# The Wait and Weight criterion
# --------------------------------------------------------------------------

class TestWaitAndWeightCriterion:
    def test_note_uses_open_hole_versus_string_volume(self):
        note = " ".join(plan_kill(examples.well_state(SV), "wait_and_weight").notes)
        assert "Open hole annular volume" in note
        assert "drill string volume" in note

    def test_no_advantage_when_open_hole_is_smaller(self):
        well = examples.well_state(SV)
        open_hole = well.annulus.volume_between(well.shoe_md, well.hole_md_ft)
        string = well.annulus.string.internal_volume_bbl
        assert open_hole < string
        note = " ".join(plan_kill(well, "wait_and_weight").notes)
        assert "no shoe-pressure advantage" in note

    def test_advantage_when_open_hole_is_larger(self):
        """Pull the bit up: the string shortens and the open hole below grows."""
        well = examples.well_state(SV).with_bit_at(6000.0)
        open_hole = well.annulus.volume_between(well.shoe_md, well.hole_md_ft)
        string = well.annulus.string.internal_volume_bbl
        assert open_hole > string
        note = " ".join(plan_kill(well, "wait_and_weight").notes)
        assert "genuinely lowers" in note

    def test_criterion_predicts_the_shoe_advantage(self):
        """Where open hole exceeds string volume, W&W really is lower."""
        well = examples.well_state(SV).with_bit_at(6000.0)
        drillers = plan_kill(well, "drillers")
        wait = plan_kill(well, "wait_and_weight")
        assert wait.peak_shoe_pressure_psi < drillers.peak_shoe_pressure_psi


# --------------------------------------------------------------------------
# with_bit_at
# --------------------------------------------------------------------------

class TestWithBitAt:
    def test_moves_the_bit(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        assert well.bit_md_ft == pytest.approx(8500.0)
        assert well.with_bit_at(10000.0).bit_md_ft == pytest.approx(10000.0)

    def test_rebuilds_the_string_volume(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        assert well.with_bit_at(10000.0).annulus.string.internal_volume_bbl > (
            well.annulus.string.internal_volume_bbl
        )

    def test_leaves_the_original_alone(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        well.with_bit_at(10000.0)
        assert well.bit_md_ft == pytest.approx(8500.0)

    def test_keeps_the_bha(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        moved = well.with_bit_at(10000.0)
        assert moved.annulus.string.components[0].od_in == (
            well.annulus.string.components[0].od_in
        )
        assert moved.annulus.string.components[0].length_ft == (
            well.annulus.string.components[0].length_ft
        )


# --------------------------------------------------------------------------
# Strip then kill
# --------------------------------------------------------------------------

class TestStripThenKill:
    @pytest.mark.parametrize("config", CONFIGS, ids=CONFIG_IDS)
    @pytest.mark.parametrize("kill", ["drillers", "wait_and_weight"])
    def test_plans_on_every_configuration(self, config, kill):
        well = examples.well_state(config, bit_off_bottom_ft=1500.0)
        sequence = strip_then_kill(well, kill)
        assert sequence.usable, sequence.blockers

    def test_kill_phase_has_the_bit_on_bottom(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        sequence = strip_then_kill(well, "drillers")
        assert sequence.well_off_bottom.bit_md_ft == pytest.approx(8500.0)
        assert sequence.well_on_bottom.bit_md_ft == pytest.approx(10000.0)

    def test_total_time_adds_both_phases(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        sequence = strip_then_kill(well, "wait_and_weight")
        strip_hours = sequence.strip.summary["Stripping time (hr)"]
        assert sequence.total_hours > strip_hours

    def test_wait_and_weight_is_the_faster_sequence(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        assert strip_then_kill(well, "wait_and_weight").total_hours < (
            strip_then_kill(well, "drillers").total_hours
        )

    def test_peak_shoe_spans_both_phases(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        sequence = strip_then_kill(well, "drillers")
        assert sequence.peak_shoe_pressure_psi >= (
            sequence.strip.peak_shoe_pressure_psi
        )
        assert sequence.peak_shoe_pressure_psi >= (
            sequence.kill.peak_shoe_pressure_psi
        )

    def test_identifies_the_worst_phase(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        assert strip_then_kill(well, "drillers").worst_phase in (
            "stripping", "the kill"
        )

    def test_stripping_is_the_worst_phase_on_the_horizontal_well(self):
        """Planning the kill in isolation would miss this."""
        well = examples.well_state(SH, bit_off_bottom_ft=1500.0)
        assert strip_then_kill(well, "drillers").worst_phase == "stripping"

    def test_summary_covers_both_phases(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        summary = strip_then_kill(well, "drillers").summary()
        for key in ("Stripping time (hr)", "Kill time (hr)", "Total time (hr)",
                    "Worst phase", "Kill mud weight (ppg)"):
            assert key in summary

    def test_non_circulating_follow_on_is_rejected(self):
        well = examples.well_state(SV, bit_off_bottom_ft=1500.0)
        with pytest.raises(ValueError, match="not a circulating kill method"):
            strip_then_kill(well, "bullhead")

    def test_blocked_when_the_bit_is_already_on_bottom(self):
        well = examples.well_state(SV)
        sequence = strip_then_kill(well, "drillers")
        assert not sequence.usable
        assert any("already on bottom" in b for b in sequence.blockers)
