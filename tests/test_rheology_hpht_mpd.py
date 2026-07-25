"""Rheology, HPHT density and MPD tests."""

import pytest

from wellcontrol import examples
from wellcontrol.hpht import (
    MudPVT,
    TemperatureProfile,
    bottomhole_pressure,
    equivalent_static_density,
    integrate_column,
    pvt_error_psi,
)
from wellcontrol.mpd import (
    DrillingWindow,
    connection_schedule,
    lightened_fluid_density,
    max_backpressure_check,
    required_backpressure,
    underbalance_psi,
)
from wellcontrol.mpd import bottomhole_pressure as mpd_bhp
from wellcontrol.rheology import (
    BinghamPlastic,
    PowerLaw,
    annular_pressure_loss,
    annular_velocity_ft_per_min,
    bit_pressure_drop,
    pipe_velocity_ft_per_min,
    string_pressure_loss,
)


# --------------------------------------------------------------------------
# Rheology
# --------------------------------------------------------------------------

class TestVelocities:
    def test_annular_velocity(self):
        """24.5 x 400 / (8.5^2 - 5^2) = 9800 / 47.25 = 207.4 ft/min"""
        assert annular_velocity_ft_per_min(400.0, 8.5, 5.0) == pytest.approx(
            207.41, abs=0.01
        )

    def test_velocity_rises_in_a_tighter_annulus(self):
        wide = annular_velocity_ft_per_min(400.0, 8.5, 5.0)
        tight = annular_velocity_ft_per_min(400.0, 8.5, 6.5)
        assert tight > wide

    def test_pipe_velocity(self):
        """24.5 x 400 / 4.276^2 = 9800 / 18.284 = 535.9 ft/min"""
        assert pipe_velocity_ft_per_min(400.0, 4.276) == pytest.approx(535.9, abs=0.5)

    def test_pipe_bigger_than_hole_is_rejected(self):
        with pytest.raises(ValueError, match="must exceed pipe OD"):
            annular_velocity_ft_per_min(400.0, 5.0, 8.5)


class TestBinghamPlastic:
    def test_from_dial_readings(self):
        """PV = 52 - 32 = 20 cP, YP = 32 - 20 = 12 lb/100ft^2"""
        mud = BinghamPlastic.from_dial_readings(52.0, 32.0)
        assert mud.plastic_viscosity_cp == pytest.approx(20.0)
        assert mud.yield_point_lb_100ft2 == pytest.approx(12.0)

    def test_critical_velocity_is_positive(self):
        mud = examples.standard_mud_rheology()
        assert mud.critical_velocity_annulus(9.6, 8.5, 5.0) > 0

    def test_laminar_below_critical_turbulent_above(self):
        """Turbulent flow costs more pressure per foot than laminar."""
        mud = examples.standard_mud_rheology()
        critical = mud.critical_velocity_annulus(9.6, 8.5, 5.0)
        low_rate = critical * (8.5 ** 2 - 5.0 ** 2) / 24.5 * 0.3
        high_rate = critical * (8.5 ** 2 - 5.0 ** 2) / 24.5 * 3.0
        low = mud.annular_gradient_psi_per_ft(low_rate, 8.5, 5.0, 9.6)
        high = mud.annular_gradient_psi_per_ft(high_rate, 8.5, 5.0, 9.6)
        assert high > low

    def test_gradient_rises_with_rate(self):
        mud = examples.standard_mud_rheology()
        gradients = [
            mud.annular_gradient_psi_per_ft(q, 8.5, 5.0, 9.6)
            for q in (100.0, 200.0, 400.0, 800.0)
        ]
        assert gradients == sorted(gradients)


class TestPowerLaw:
    def test_fit_from_dial_readings(self):
        """n_pipe = 3.32 x log10(52/32) = 0.700
        n_annulus = 0.657 x log10(15/4) = 0.377
        """
        mud = PowerLaw.from_dial_readings(52.0, 32.0, 15.0, 4.0)
        assert mud.n_pipe == pytest.approx(0.700, abs=0.005)
        assert mud.n_annulus == pytest.approx(0.377, abs=0.005)
        assert mud.k_pipe > 0
        assert mud.k_annulus > 0

    def test_zero_reading_is_rejected(self):
        with pytest.raises(ValueError, match="must be positive"):
            PowerLaw.from_dial_readings(52.0, 32.0, 15.0, 0.0)

    def test_gradient_rises_with_rate(self):
        mud = PowerLaw.from_dial_readings(52.0, 32.0, 15.0, 4.0)
        low = mud.annular_gradient_psi_per_ft(200.0, 8.5, 5.0)
        high = mud.annular_gradient_psi_per_ft(600.0, 8.5, 5.0)
        assert high > low


class TestWholeSystemLosses:
    def test_annular_loss_is_positive_and_rate_dependent(self):
        annulus, _ = examples.vertical_land_well()
        mud = examples.standard_mud_rheology()
        low = annular_pressure_loss(annulus, 200.0, mud, mud_weight_ppg=9.6)
        high = annular_pressure_loss(annulus, 500.0, mud, mud_weight_ppg=9.6)
        assert 0 < low < high

    def test_annular_loss_excludes_below_the_bit_by_default(self):
        annulus, _ = examples.vertical_land_well()
        mud = examples.standard_mud_rheology()
        loss = annular_pressure_loss(annulus, 300.0, mud, mud_weight_ppg=9.6)
        partial = annular_pressure_loss(
            annulus, 300.0, mud, mud_weight_ppg=9.6, bottom_md=5000.0
        )
        assert partial < loss

    def test_bingham_without_mud_weight_is_rejected(self):
        annulus, _ = examples.vertical_land_well()
        with pytest.raises(ValueError, match="needs mud_weight_ppg"):
            annular_pressure_loss(annulus, 300.0, examples.standard_mud_rheology())

    def test_power_law_needs_no_mud_weight(self):
        annulus, _ = examples.vertical_land_well()
        mud = PowerLaw.from_dial_readings(52.0, 32.0, 15.0, 4.0)
        assert annular_pressure_loss(annulus, 300.0, mud) > 0

    def test_string_loss_is_positive(self):
        annulus, _ = examples.vertical_land_well()
        mud = examples.standard_mud_rheology()
        assert string_pressure_loss(annulus.string, 300.0, mud, 9.6) > 0

    def test_string_loss_far_exceeds_annular_loss(self):
        """Small bores and high velocities inside the pipe; big bores and low
        velocities outside it.
        """
        annulus, _ = examples.vertical_land_well()
        mud = examples.standard_mud_rheology()
        inside = string_pressure_loss(annulus.string, 300.0, mud, 9.6)
        outside = annular_pressure_loss(annulus, 300.0, mud, mud_weight_ppg=9.6)
        assert inside > outside


class TestBitPressureDrop:
    def test_three_twelfths(self):
        """Area = 3 x pi/4 x (12/32)^2 = 0.33134 in^2
        dP = 9.6 x 400^2 / (12042 x 0.95^2 x 0.33134^2) = 1287 psi
        """
        assert bit_pressure_drop(400.0, 9.6, [12, 12, 12]) == pytest.approx(
            1287.4, abs=2.0
        )

    def test_bigger_nozzles_drop_less(self):
        small = bit_pressure_drop(400.0, 9.6, [11, 11, 11])
        big = bit_pressure_drop(400.0, 9.6, [16, 16, 16])
        assert big < small

    def test_no_nozzles_is_rejected(self):
        with pytest.raises(ValueError, match="At least one nozzle"):
            bit_pressure_drop(400.0, 9.6, [])


# --------------------------------------------------------------------------
# HPHT
# --------------------------------------------------------------------------

class TestTemperatureProfile:
    def test_linear_gradient(self):
        """70 degF surface, 1.5 degF/100ft, at 20000 ft:
        70 + 1.5 x 200 = 370 degF
        """
        profile = TemperatureProfile(surface_temp_f=70.0, gradient_f_per_100ft=1.5)
        assert profile.temperature_at(20000.0) == pytest.approx(370.0)

    def test_fit_to_a_measured_bottomhole_temperature(self):
        profile = TemperatureProfile.from_bottomhole(70.0, 370.0, 20000.0)
        assert profile.gradient_f_per_100ft == pytest.approx(1.5)
        assert profile.temperature_at(20000.0) == pytest.approx(370.0)

    def test_subsea_datum_starts_at_the_mudline(self):
        """Below a cold seabed the rock is at seabed temperature, not surface."""
        profile = TemperatureProfile(
            surface_temp_f=40.0, gradient_f_per_100ft=1.5, datum_tvd_ft=5075.0
        )
        assert profile.temperature_at(5075.0) == pytest.approx(40.0)
        assert profile.temperature_at(15075.0) == pytest.approx(190.0)


class TestMudPVT:
    def test_density_at_downhole_conditions(self):
        """14.0 x [1 + 3.5e-6 x (15000 - 14.7) - 2.6e-4 x (300 - 70)]
        = 14.0 x [1 + 0.052449 - 0.0598] = 14.0 x 0.992649 = 13.897 ppg
        """
        mud = MudPVT(
            surface_density_ppg=14.0,
            compressibility_per_psi=3.5e-6,
            thermal_expansion_per_f=2.6e-4,
        )
        assert mud.density_at(15000.0, 300.0) == pytest.approx(13.897, abs=0.005)

    def test_pressure_alone_makes_mud_heavier(self):
        mud = MudPVT(surface_density_ppg=14.0)
        assert mud.density_at(15000.0, 70.0) > 14.0

    def test_temperature_alone_makes_mud_lighter(self):
        mud = MudPVT(surface_density_ppg=14.0)
        assert mud.density_at(14.7, 300.0) < 14.0

    def test_oil_based_is_more_sensitive_than_water_based(self):
        obm = MudPVT.typical(14.0, "oil_based")
        wbm = MudPVT.typical(14.0, "water_based")
        obm_swing = abs(obm.density_at(15000.0, 350.0) - 14.0)
        wbm_swing = abs(wbm.density_at(15000.0, 350.0) - 14.0)
        assert obm_swing > wbm_swing

    def test_unknown_mud_type_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown mud type"):
            MudPVT.typical(14.0, "gravy")


class TestIntegratedColumn:
    def test_pressure_increases_monotonically(self):
        mud = MudPVT.typical(14.0, "oil_based")
        profile = TemperatureProfile(70.0, 1.5)
        steps = integrate_column(mud, profile, 20000.0, step_ft=1000.0)
        pressures = [s.pressure_psi for s in steps]
        assert pressures == sorted(pressures)
        assert steps[0].tvd_ft == pytest.approx(0.0)
        assert steps[-1].tvd_ft == pytest.approx(20000.0)

    def test_hot_well_reads_lighter_than_the_pit(self):
        """At 20000 ft and 370 degF, thermal expansion beats compression for an
        oil-based mud, so real bottomhole pressure is *below* the simple
        calculation. That is the dangerous direction.
        """
        mud = MudPVT.typical(14.0, "oil_based")
        profile = TemperatureProfile(70.0, 1.5)
        error = pvt_error_psi(mud, profile, 20000.0, step_ft=500.0)
        assert error < 0
        esd = equivalent_static_density(mud, profile, 20000.0, step_ft=500.0)
        assert esd < 14.0

    def test_cold_deep_well_reads_heavier(self):
        """With a low geothermal gradient compression wins instead."""
        mud = MudPVT.typical(14.0, "oil_based")
        profile = TemperatureProfile(70.0, 0.4)
        assert pvt_error_psi(mud, profile, 20000.0, step_ft=500.0) > 0

    def test_error_is_significant_at_hpht_conditions(self):
        """Hundreds of psi -- comparable to the whole drilling window."""
        mud = MudPVT.typical(14.0, "oil_based")
        profile = TemperatureProfile(70.0, 1.5)
        assert abs(pvt_error_psi(mud, profile, 20000.0, step_ft=500.0)) > 100.0

    def test_surface_pressure_carries_through_and_then_some(self):
        """500 psi at surface arrives at bottom as slightly *more* than 500 psi.

        The extra pressure compresses the whole mud column, which makes it
        denser, which adds hydrostatic of its own. About 19 psi of gain here.
        This is a real effect, not a numerical artefact -- with a constant
        density model the difference would be exactly 500.
        """
        mud = MudPVT.typical(14.0)
        profile = TemperatureProfile(70.0, 1.5)
        with_sp = bottomhole_pressure(mud, profile, 15000.0, 500.0, step_ft=500.0)
        without = bottomhole_pressure(mud, profile, 15000.0, 0.0, step_ft=500.0)
        gain = with_sp - without
        assert 500.0 < gain < 530.0

    def test_bad_depth_range_is_rejected(self):
        mud = MudPVT.typical(14.0)
        profile = TemperatureProfile(70.0, 1.5)
        with pytest.raises(ValueError, match="below the top of the column"):
            integrate_column(mud, profile, 100.0, top_tvd_ft=5000.0)


# --------------------------------------------------------------------------
# MPD
# --------------------------------------------------------------------------

class TestMpdPressures:
    def test_bottomhole_pressure_sums_three_terms(self):
        """0.052 x 9.6 x 10000 + 200 + 150 = 4992 + 350 = 5342 psi"""
        assert mpd_bhp(9.6, 10000.0, 200.0, 150.0) == pytest.approx(5342.0)

    def test_required_backpressure(self):
        """5200 - 4992 - 200 = 8 psi"""
        assert required_backpressure(5200.0, 9.6, 10000.0, 200.0) == pytest.approx(8.0)

    def test_negative_backpressure_signals_mud_too_heavy(self):
        assert required_backpressure(5000.0, 9.6, 10000.0, 200.0) < 0


class TestDrillingWindow:
    def test_width(self):
        """(13.0 - 12.0 - 2 x 0.2) = 0.6 ppg
        0.052 x 0.6 x 15000 = 468 psi
        """
        window = DrillingWindow(12.0, 13.0, 15000.0, safety_margin_ppg=0.2)
        assert window.width_ppg == pytest.approx(0.6)
        assert window.width_psi == pytest.approx(468.0)

    def test_inverted_window_is_rejected(self):
        with pytest.raises(ValueError, match="no window here at all"):
            DrillingWindow(13.0, 12.0, 15000.0)

    def test_is_within(self):
        window = DrillingWindow(12.0, 13.0, 15000.0, safety_margin_ppg=0.2)
        assert window.is_within(9600.0)
        assert not window.is_within(8000.0)
        assert not window.is_within(11000.0)

    def test_narrow_window_needs_mpd(self):
        """If the ECD swing is wider than the whole window, no single mud
        weight is safe both circulating and static.
        """
        narrow = DrillingWindow(12.0, 12.3, 15000.0)
        wide = DrillingWindow(12.0, 14.0, 15000.0)
        assert narrow.needs_mpd(annular_friction_psi=400.0)
        assert not wide.needs_mpd(annular_friction_psi=400.0)


class TestConnectionSchedule:
    def test_bottomhole_pressure_stays_constant(self):
        schedule = connection_schedule(
            target_bhp_psi=9700.0,
            mud_weight_ppg=12.0,
            tvd_ft=15000.0,
            full_rate_gpm=600.0,
            full_rate_friction_psi=300.0,
            steps=6,
        )
        for step in schedule:
            assert step.bottomhole_pressure_psi == pytest.approx(9700.0, abs=0.01)

    def test_backpressure_rises_as_the_pumps_come_down(self):
        schedule = connection_schedule(9700.0, 12.0, 15000.0, 600.0, 300.0, steps=6)
        pressures = [s.surface_backpressure_psi for s in schedule]
        assert pressures == sorted(pressures)

    def test_friction_falls_with_the_square_of_rate(self):
        """At half rate, friction is a quarter: 300 -> 75 psi."""
        schedule = connection_schedule(9700.0, 12.0, 15000.0, 600.0, 300.0, steps=2)
        assert schedule[1].annular_friction_psi == pytest.approx(75.0)

    def test_pumps_off_has_no_friction(self):
        schedule = connection_schedule(9700.0, 12.0, 15000.0, 600.0, 300.0, steps=4)
        assert schedule[-1].flow_rate_gpm == pytest.approx(0.0)
        assert schedule[-1].annular_friction_psi == pytest.approx(0.0)

    def test_rcd_rating_check_flags_an_overpressure(self):
        schedule = connection_schedule(9700.0, 11.0, 15000.0, 600.0, 300.0, steps=4)
        warnings = max_backpressure_check(schedule, rcd_rating_psi=500.0)
        assert any("exceeds the RCD rating" in w for w in warnings)

    def test_rcd_rating_check_passes_a_good_schedule(self):
        """11.9 ppg over 15000 ft gives 9282 psi of hydrostatic, so the choke
        holds 118 psi at full rate rising to 418 psi with the pumps off. Both
        positive and both well inside the rating.
        """
        schedule = connection_schedule(9700.0, 11.9, 15000.0, 600.0, 300.0, steps=4)
        assert max_backpressure_check(schedule, rcd_rating_psi=2000.0) == []


class TestUnderbalanced:
    def test_underbalance_is_positive_when_the_well_will_flow(self):
        """Pore 5000 psi against 4992 psi of mud = 8 psi underbalanced."""
        assert underbalance_psi(5000.0, 9.6, 10000.0) == pytest.approx(8.0)

    def test_backpressure_can_kill_the_underbalance(self):
        assert underbalance_psi(5000.0, 9.6, 10000.0, 0.0, 200.0) < 0

    def test_gas_lightens_the_fluid(self):
        """30% downhole gas by volume in 9 ppg brine:
        0.7 x 9.0 + 0.3 x 0.1 = 6.33 ppg
        """
        assert lightened_fluid_density(9.0, 0.30) == pytest.approx(6.33, abs=0.001)

    def test_gas_fraction_must_be_a_fraction(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            lightened_fluid_density(9.0, 1.5)
