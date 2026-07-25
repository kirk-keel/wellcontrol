"""Kick tolerance, MAASP and subsea correction tests."""

import pytest

from wellcontrol import examples
from wellcontrol.subsea import (
    SubseaGeometry,
    choke_line_friction_measured,
    corrected_initial_circulating_pressure,
    hydrostatic_loss_on_disconnect,
    pressure_at_wellhead,
    riser_margin_ppg,
    subsea_maasp,
)
from wellcontrol.tolerance import (
    KickTolerance,
    frac_gradient_from_leak_off,
    frac_pressure_at_shoe,
    maasp,
)


# --------------------------------------------------------------------------
# Formation strength
# --------------------------------------------------------------------------

class TestFormationStrength:
    def test_frac_gradient_from_lot(self):
        """9.0 ppg mud, 1400 psi leak-off at a 7000 ft shoe:
        9.0 + 1400 / (0.052 x 7000) = 9.0 + 3.846 = 12.846 ppg
        """
        assert frac_gradient_from_leak_off(9.0, 1400.0, 7000.0) == (
            pytest.approx(12.8462, abs=0.001)
        )

    def test_frac_pressure_cross_checks(self):
        """0.052 x 9.0 x 7000 + 1400 = 3276 + 1400 = 4676 psi"""
        fg = frac_gradient_from_leak_off(9.0, 1400.0, 7000.0)
        assert frac_pressure_at_shoe(fg, 7000.0) == pytest.approx(4676.0, abs=0.1)

    def test_zero_shoe_depth_is_rejected(self):
        with pytest.raises(ValueError, match="must be positive"):
            frac_gradient_from_leak_off(9.0, 1400.0, 0.0)


class TestMaasp:
    def test_maasp(self):
        """(12.846 - 9.6) x 0.052 x 7000 = 1181.6, reported as 1181.

        MAASP is a limit, so it rounds DOWN to a whole psi. Rounding up would
        claim margin the well does not have.
        """
        assert maasp(12.8462, 9.6, 7000.0) == 1181

    def test_maasp_returns_a_whole_number(self):
        assert isinstance(maasp(12.8462, 9.6, 7000.0), int)

    def test_max_allowable_mud_weight_rounds_down(self):
        """12.8462 gives an MAMW of 12.8, not 12.9."""
        from wellcontrol.tolerance import max_allowable_mud_weight

        assert max_allowable_mud_weight(12.8462) == pytest.approx(12.8)

    def test_maasp_falls_as_mud_weight_rises(self):
        """Weighting up to kill the well eats the margin needed to kill it."""
        before = maasp(12.8462, 9.6, 7000.0)
        after = maasp(12.8462, 10.37, 7000.0)
        assert after < before
        assert before - after == pytest.approx(0.77 * 0.052 * 7000.0, abs=1.0)


# --------------------------------------------------------------------------
# Kick tolerance
# --------------------------------------------------------------------------

class TestKickTolerance:
    def test_frac_pressure(self):
        kt = examples.vertical_land_well_kick_tolerance()
        assert kt.frac_pressure_psi == pytest.approx(4676.0, abs=0.5)

    def test_max_formation_pressure(self):
        """4676 + 0.052 x 9.6 x 3000 = 4676 + 1497.6 = 6173.6 psi"""
        kt = examples.vertical_land_well_kick_tolerance()
        assert kt.max_formation_pressure_psi == pytest.approx(6173.6, abs=0.5)

    def test_kick_intensity(self):
        """6173.6 / 520 - 9.6 = 11.872 - 9.6 = 2.272 ppg"""
        kt = examples.vertical_land_well_kick_tolerance()
        assert kt.kick_intensity_ppg == pytest.approx(2.272, abs=0.005)

    def test_max_influx_height(self):
        """(4676 - 5392 + 0.4992 x 3000) / (0.4992 - 0.1)
        = 781.6 / 0.3992 = 1957.9 ft
        """
        kt = examples.vertical_land_well_kick_tolerance()
        assert kt.max_influx_height_ft(5392.0) == pytest.approx(1957.9, abs=2.0)

    def test_gas_expands_so_the_safe_volume_at_bottom_is_smaller(self):
        """The volume that is safe at the shoe is larger than the volume that
        is safe when taken, because the gas expands on the way up.
        """
        kt = examples.vertical_land_well_kick_tolerance()
        at_shoe = kt.max_influx_volume_at_shoe_bbl(5392.0)
        at_td = kt.max_influx_volume_at_td_bbl(5392.0)
        assert at_td < at_shoe

    def test_max_influx_volume_at_td(self):
        """1957.9 ft x 0.0489215 bbl/ft = 95.78 bbl at the shoe.
        Boyle back to bottom: 95.78 x (4676 + 97.9 + 14.7) / (5392 + 14.7)
        = 95.78 x 0.8857 = 84.8 bbl
        """
        kt = examples.vertical_land_well_kick_tolerance()
        assert kt.max_influx_volume_at_td_bbl(5392.0) == pytest.approx(84.8, abs=1.0)

    def test_bigger_kick_intensity_means_smaller_tolerable_gain(self):
        kt = examples.vertical_land_well_kick_tolerance()
        assert kt.max_pit_gain_bbl(1.5) < kt.max_pit_gain_bbl(0.5)

    def test_shoe_below_td_is_rejected(self):
        with pytest.raises(ValueError, match="shoe must be above total depth"):
            KickTolerance(
                mud_weight_ppg=9.6,
                frac_gradient_ppg=12.8,
                shoe_tvd_ft=10000.0,
                hole_tvd_ft=7000.0,
                annular_capacity_at_shoe_bbl_per_ft=0.05,
                annular_capacity_at_td_bbl_per_ft=0.03,
            )

    def test_mud_above_frac_gradient_is_rejected(self):
        with pytest.raises(ValueError, match="no kick tolerance"):
            KickTolerance(
                mud_weight_ppg=13.0,
                frac_gradient_ppg=12.8,
                shoe_tvd_ft=7000.0,
                hole_tvd_ft=10000.0,
                annular_capacity_at_shoe_bbl_per_ft=0.05,
                annular_capacity_at_td_bbl_per_ft=0.03,
            )

    def test_formation_pressure_above_the_limit_is_rejected(self):
        kt = examples.vertical_land_well_kick_tolerance()
        with pytest.raises(ValueError, match="no kick tolerance at this depth"):
            kt.max_influx_height_ft(7000.0)

    def test_summary_includes_volumes_when_given_a_pressure(self):
        kt = examples.vertical_land_well_kick_tolerance()
        assert "Max influx volume when taken (bbl)" not in kt.summary()
        assert "Max influx volume when taken (bbl)" in kt.summary(5392.0)


# --------------------------------------------------------------------------
# Subsea
# --------------------------------------------------------------------------

class TestSubseaGeometry:
    def test_mudline_depth(self):
        geom = examples.deepwater_geometry()
        assert geom.mudline_tvd_ft == pytest.approx(5075.0)

    def test_seawater_hydrostatic(self):
        """0.052 x 8.55 x 5000 = 2223 psi"""
        geom = examples.deepwater_geometry()
        assert geom.seawater_hydrostatic_psi == pytest.approx(2223.0)


class TestChokeLine:
    def test_measured_friction_is_the_difference(self):
        assert choke_line_friction_measured(900.0, 1250.0) == pytest.approx(350.0)

    def test_choke_line_reading_below_riser_is_rejected(self):
        with pytest.raises(ValueError, match="not physical"):
            choke_line_friction_measured(1250.0, 900.0)

    def test_corrected_icp_subtracts_friction(self):
        """500 + 900 - 350 = 1050 psi, not 1400."""
        assert corrected_initial_circulating_pressure(500.0, 900.0, 350.0) == (
            pytest.approx(1050.0)
        )

    def test_kill_sheet_applies_the_correction(self):
        with_clf = examples.deepwater_kill_sheet(350.0)
        without = examples.deepwater_kill_sheet(0.0)
        assert without.initial_circulating_pressure_psi - (
            with_clf.initial_circulating_pressure_psi
        ) == pytest.approx(350.0)
        assert without.final_circulating_pressure_psi - (
            with_clf.final_circulating_pressure_psi
        ) == pytest.approx(350.0)


class TestRiserMargin:
    def test_riser_margin(self):
        """(12.5 x 15000 - 8.55 x 5000) / (15000 - 5075) - 12.5
        = (187500 - 42750) / 9925 - 12.5
        = 14.584 - 12.5 = 2.084 ppg
        """
        geom = examples.deepwater_geometry()
        assert riser_margin_ppg(12.5, 15000.0, geom) == pytest.approx(2.084, abs=0.005)

    def test_hydrostatic_loss_on_disconnect(self):
        """Connected:    0.052 x 12.5 x 15000 = 9750 psi
        Disconnected: 0.052 x 12.5 x 9925 + 0.052 x 8.55 x 5000
                    = 6451.25 + 2223 = 8674.25 psi
        Loss = 1075.75 psi
        """
        geom = examples.deepwater_geometry()
        assert hydrostatic_loss_on_disconnect(12.5, 15000.0, geom) == (
            pytest.approx(1075.75, abs=0.5)
        )

    def test_riser_margin_grows_with_water_depth(self):
        shallow = SubseaGeometry(air_gap_ft=75.0, water_depth_ft=500.0)
        deep = SubseaGeometry(air_gap_ft=75.0, water_depth_ft=8000.0)
        assert riser_margin_ppg(12.5, 15000.0, deep) > riser_margin_ppg(
            12.5, 15000.0, shallow
        )

    def test_formation_above_the_mudline_is_rejected(self):
        geom = examples.deepwater_geometry()
        with pytest.raises(ValueError, match="at or above the mudline"):
            riser_margin_ppg(12.5, 4000.0, geom)


class TestSubseaPressures:
    def test_subsea_maasp(self):
        assert subsea_maasp(14.0, 12.5, 11000.0) == pytest.approx(858.0, abs=0.5)

    def test_pressure_at_the_stack_includes_the_column_above_it(self):
        """1000 psi at the rig floor plus 0.052 x 12.5 x 5075 = 3298.75 psi
        of mud gives 4298.75 psi at the BOP.
        """
        geom = examples.deepwater_geometry()
        assert pressure_at_wellhead(1000.0, 12.5, geom) == pytest.approx(
            4298.75, abs=0.5
        )
