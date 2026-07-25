"""Geometry, capacity and pump tests.

Expected values are computed by hand in the docstrings so they can be checked
independently of the code.
"""

import pytest

from wellcontrol import examples
from wellcontrol.geometry import (
    Annulus,
    DrillString,
    HoleSection,
    Pipe,
    Pump,
    Wellbore,
    annular_capacity_bbl_per_ft,
    capacity_bbl_per_ft,
    closed_end_displacement_bbl_per_ft,
    metal_displacement_bbl_per_ft,
)


class TestCapacities:
    def test_drill_pipe_capacity(self):
        """4.276 in ID: 4.276^2 / 1029.4 = 18.284176 / 1029.4 = 0.0177620"""
        assert capacity_bbl_per_ft(4.276) == pytest.approx(0.0177620, abs=1e-6)

    def test_annular_capacity(self):
        """8.5 in hole, 5 in pipe: (72.25 - 25) / 1029.4 = 47.25 / 1029.4
        = 0.0459005
        """
        assert annular_capacity_bbl_per_ft(8.5, 5.0) == pytest.approx(
            0.0459005, abs=1e-6
        )

    def test_metal_displacement(self):
        """5 in x 4.276 in: (25 - 18.284176) / 1029.4 = 0.0065242"""
        assert metal_displacement_bbl_per_ft(5.0, 4.276) == pytest.approx(
            0.0065242, abs=1e-6
        )

    def test_closed_end_exceeds_open_end(self):
        """Running on a float displaces the full OD, not just the steel."""
        closed = closed_end_displacement_bbl_per_ft(5.0)
        open_ended = metal_displacement_bbl_per_ft(5.0, 4.276)
        assert closed > open_ended
        assert closed == pytest.approx(25.0 / 1029.4, abs=1e-9)

    def test_pipe_larger_than_hole_is_rejected(self):
        with pytest.raises(ValueError, match="larger than hole ID"):
            annular_capacity_bbl_per_ft(5.0, 8.5)


class TestPipe:
    def test_id_cannot_exceed_od(self):
        with pytest.raises(ValueError, match="exceeds OD"):
            Pipe(name="bad", od_in=4.0, id_in=5.0, length_ft=100.0)

    def test_volume(self):
        pipe = Pipe(name="dp", od_in=5.0, id_in=4.276, length_ft=1000.0)
        assert pipe.volume_bbl == pytest.approx(17.7620, abs=1e-3)


class TestDrillString:
    def test_from_bha_fills_to_bit_depth(self):
        collars = Pipe("collars", 6.5, 2.8125, 600.0)
        dp = Pipe("dp", 5.0, 4.276, 0.0)
        string = DrillString.from_bha([collars], dp, 10000.0)
        assert string.components[-1].length_ft == pytest.approx(9400.0)
        assert sum(c.length_ft for c in string.components) == pytest.approx(10000.0)

    def test_internal_volume(self):
        """9400 ft DP at 0.0177620 = 166.963 bbl
        600 ft DC at 2.8125^2/1029.4 = 0.0076842 -> 4.611 bbl
        Total 171.573 bbl
        """
        annulus, _ = examples.vertical_land_well()
        assert annulus.string.internal_volume_bbl == pytest.approx(171.573, abs=0.01)

    def test_length_mismatch_is_rejected(self):
        collars = Pipe("collars", 6.5, 2.8125, 600.0)
        with pytest.raises(ValueError, match="does not reach the bit depth"):
            DrillString(components=[collars], bit_depth_md=10000.0)

    def test_bha_longer_than_hole_is_rejected(self):
        collars = Pipe("collars", 6.5, 2.8125, 600.0)
        dp = Pipe("dp", 5.0, 4.276, 0.0)
        with pytest.raises(ValueError, match="exceeds bit depth"):
            DrillString.from_bha([collars], dp, 400.0)

    def test_pipe_od_at_depth(self):
        annulus, _ = examples.vertical_land_well()
        string = annulus.string
        assert string.pipe_od_at(5000.0) == pytest.approx(5.0)
        assert string.pipe_od_at(9800.0) == pytest.approx(6.5)


class TestWellbore:
    def test_gap_between_sections_is_rejected(self):
        with pytest.raises(ValueError, match="Gap or overlap"):
            Wellbore([
                HoleSection("csg", 8.681, 0.0, 7000.0),
                HoleSection("oh", 8.5, 7500.0, 10000.0, is_open_hole=True),
            ])

    def test_must_start_at_surface(self):
        with pytest.raises(ValueError, match="must start at MD 0"):
            Wellbore([HoleSection("oh", 8.5, 100.0, 10000.0)])

    def test_shoe_depth(self):
        annulus, _ = examples.vertical_land_well()
        assert annulus.wellbore.shoe_md == pytest.approx(7000.0)

    def test_hole_id_at_depth(self):
        annulus, _ = examples.vertical_land_well()
        assert annulus.wellbore.hole_id_at(3000.0) == pytest.approx(8.681)
        assert annulus.wellbore.hole_id_at(8000.0) == pytest.approx(8.5)


class TestAnnulus:
    def test_interval_split_at_every_geometry_change(self):
        """Casing shoe at 7000 and top of collars at 9400 both create breaks."""
        annulus, _ = examples.vertical_land_well()
        boundaries = [i.top_md for i in annulus.intervals] + [
            annulus.intervals[-1].bottom_md
        ]
        for expected in (0.0, 7000.0, 9400.0, 10000.0):
            assert any(abs(b - expected) < 1e-6 for b in boundaries)

    def test_total_volume(self):
        """0-7000 casing/DP:   (8.681^2-25)/1029.4 = 0.0489215 x 7000 = 342.450
        7000-9400 OH/DP:       (72.25-25)/1029.4  = 0.0458995 x 2400 = 110.159
        9400-10000 OH/collars: (72.25-42.25)/1029.4 = 0.0291432 x 600 = 17.486
        Total = 470.095 bbl
        """
        annulus, _ = examples.vertical_land_well()
        assert annulus.volume_bbl == pytest.approx(470.095, abs=0.01)

    def test_volume_between_matches_total(self):
        annulus, _ = examples.vertical_land_well()
        assert annulus.volume_between(0.0, 10000.0) == pytest.approx(
            annulus.volume_bbl, abs=1e-6
        )

    def test_capacity_changes_across_the_collars(self):
        annulus, _ = examples.vertical_land_well()
        assert annulus.capacity_at(9000.0) == pytest.approx(0.0459005, abs=1e-6)
        assert annulus.capacity_at(9800.0) == pytest.approx(0.0291432, abs=1e-6)

    def test_height_of_volume_spans_the_capacity_change(self):
        """20 bbl on bottom: the collar annulus holds 600 x 0.0291432 = 17.486
        bbl, so 2.514 bbl spills into the wider section above at 0.0458995
        bbl/ft = 54.77 ft. Total height 654.77 ft.

        Treating the annulus as uniformly 0.0458995 would give 435.7 ft, a
        33% under-estimate of the influx height.
        """
        annulus, _ = examples.vertical_land_well()
        height = annulus.height_of_volume_from_bottom(20.0)
        assert height == pytest.approx(654.77, abs=0.1)

    def test_volume_within_one_interval(self):
        annulus, _ = examples.vertical_land_well()
        height = annulus.height_of_volume_from_bottom(10.0)
        assert height == pytest.approx(10.0 / 0.0291432, abs=0.1)

    def test_overfilling_the_annulus_is_rejected(self):
        annulus, _ = examples.vertical_land_well()
        with pytest.raises(ValueError, match="exceeds the total annular volume"):
            annulus.height_of_volume_from_bottom(10000.0)

    def test_bit_above_total_depth_leaves_open_rathole(self):
        wellbore = Wellbore([
            HoleSection("csg", 8.681, 0.0, 7000.0),
            HoleSection("oh", 8.5, 7000.0, 10000.0, is_open_hole=True),
        ])
        collars = Pipe("collars", 6.5, 2.8125, 600.0)
        dp = Pipe("dp", 5.0, 4.276, 0.0)
        string = DrillString.from_bha([collars], dp, 9500.0)
        annulus = Annulus(wellbore, string)
        # Below the bit there is no pipe, so capacity is the full hole.
        assert annulus.capacity_at(9800.0) == pytest.approx(72.25 / 1029.4, abs=1e-6)


class TestPump:
    def test_triplex_output(self):
        """0.000243 x 6.5^2 x 12 x 0.95
        = 0.000243 x 42.25 x 12 x 0.95 = 0.1170410 bbl/stk
        """
        pump = examples.standard_pump()
        assert pump.output_bbl_per_stroke == pytest.approx(0.1170410, abs=1e-6)

    def test_duplex_output(self):
        """0.000162 x 12 x (2 x 6^2 - 2^2) x 1.0
        = 0.000162 x 12 x 68 = 0.132192 bbl/stk
        """
        pump = Pump(
            liner_id_in=6.0,
            stroke_length_in=12.0,
            efficiency=1.0,
            kind="duplex",
            rod_od_in=2.0,
        )
        assert pump.output_bbl_per_stroke == pytest.approx(0.132192, abs=1e-6)

    def test_strokes_and_volume_round_trip(self):
        pump = examples.standard_pump()
        assert pump.volume_for(pump.strokes_for(250.0)) == pytest.approx(250.0)

    def test_flow_rate(self):
        """0.1170410 bbl/stk x 30 spm x 42 gal/bbl = 147.5 gpm"""
        pump = examples.standard_pump()
        assert pump.flow_rate_gpm(30.0) == pytest.approx(147.47, abs=0.01)

    def test_spm_for_flow_inverts_flow_rate(self):
        pump = examples.standard_pump()
        assert pump.spm_for_flow(pump.flow_rate_gpm(42.0)) == pytest.approx(42.0)

    def test_unknown_pump_type_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown pump type"):
            Pump(liner_id_in=6.0, stroke_length_in=12.0, kind="quintuplex")

    def test_duplex_rod_must_fit(self):
        with pytest.raises(ValueError, match="Rod OD must be smaller"):
            Pump(
                liner_id_in=6.0,
                stroke_length_in=12.0,
                kind="duplex",
                rod_od_in=6.0,
            )
