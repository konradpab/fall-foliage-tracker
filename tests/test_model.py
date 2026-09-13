"""Fixed inputs -> fixed outputs. The model is pure, so these are exact."""

from datetime import date, timedelta

import pytest

from batch import config as C
from batch.model import (
    DailyWeather,
    advance_state,
    baseline_peak_doy,
    classify,
    confidence_for,
    first_hard_freeze,
    predict_cell,
    weather_shift,
)


def series(start: date, days: int, tmin: float, tmax: float) -> list[DailyWeather]:
    return [DailyWeather(start + timedelta(days=i), tmin, tmax) for i in range(days)]


# --- baseline -------------------------------------------------------------

def test_baseline_is_later_further_south():
    assert baseline_peak_doy(45.0, 0) > baseline_peak_doy(60.0, 0)


def test_baseline_is_earlier_higher_up():
    assert baseline_peak_doy(47.0, 2000) < baseline_peak_doy(47.0, 200)


def test_baseline_warsaw_is_mid_october():
    # 52.25N, 110 m -> 20 October (day 293) by the documented constants.
    doy = baseline_peak_doy(52.25, 110)
    assert round(doy) == 293
    assert date(2026, 1, 1) + timedelta(days=round(doy) - 1) == date(2026, 10, 20)


def test_baseline_unknown_elevation_is_treated_as_sea_level():
    assert baseline_peak_doy(52.25, None) == baseline_peak_doy(52.25, 0)


def test_baseline_below_sea_level_does_not_delay_peak():
    # A -5 m polder must not read as "5 m of negative altitude" and shift later.
    assert baseline_peak_doy(52.0, -5) == baseline_peak_doy(52.0, 0)


def test_baseline_is_clamped_to_the_calendar_window():
    assert baseline_peak_doy(20.0, 0) == C.BASELINE_DOY_MAX
    assert baseline_peak_doy(85.0, 0) == C.BASELINE_DOY_MIN


# --- weather shift --------------------------------------------------------

def test_cool_nights_advance_the_peak():
    daily = series(date(2026, 9, 1), 10, tmin=3.0, tmax=14.0)
    shift, cool, warm = weather_shift(daily, date(2026, 9, 10))
    assert (cool, warm) == (10, 0)
    assert shift == pytest.approx(10 * C.COOL_NIGHT_SHIFT)
    assert shift < 0


def test_warm_days_delay_the_peak():
    daily = series(date(2026, 9, 1), 10, tmin=12.0, tmax=30.0)
    shift, cool, warm = weather_shift(daily, date(2026, 9, 10))
    assert (cool, warm) == (0, 10)
    assert shift == pytest.approx(10 * C.WARM_DAY_SHIFT)


def test_shift_is_capped_both_ways():
    cold = series(date(2026, 9, 1), 60, tmin=0.0, tmax=8.0)
    hot = series(date(2026, 9, 1), 60, tmin=15.0, tmax=32.0)
    assert weather_shift(cold, date(2026, 10, 30))[0] == -C.MAX_ABS_SHIFT
    assert weather_shift(hot, date(2026, 10, 30))[0] == C.MAX_ABS_SHIFT


def test_days_before_september_are_ignored():
    daily = series(date(2026, 8, 1), 31, tmin=2.0, tmax=10.0)
    assert weather_shift(daily, date(2026, 8, 31)) == (0.0, 0, 0)


def test_window_end_stops_accumulation_at_the_peak():
    daily = series(date(2026, 9, 1), 90, tmin=3.0, tmax=14.0)
    early = weather_shift(daily, date(2026, 11, 30), window_end=date(2026, 10, 15))
    late = weather_shift(daily, date(2026, 12, 20), window_end=date(2026, 10, 15))
    assert early == late, "the estimate must stop moving once the peak has passed"


def test_missing_temperatures_are_skipped_not_counted():
    daily = [DailyWeather(date(2026, 9, i + 1), None, None) for i in range(10)]
    assert weather_shift(daily, date(2026, 9, 10)) == (0.0, 0, 0)


# --- hard freeze ----------------------------------------------------------

def test_first_hard_freeze_is_found():
    daily = series(date(2026, 9, 1), 30, tmin=5.0, tmax=12.0)
    daily[20] = DailyWeather(date(2026, 9, 21), -6.0, 1.0)
    assert first_hard_freeze(daily, date(2026, 9, 30)) == date(2026, 9, 21)


def test_future_freeze_is_not_counted_as_having_happened():
    daily = series(date(2026, 9, 1), 30, tmin=5.0, tmax=12.0)
    daily[25] = DailyWeather(date(2026, 9, 26), -6.0, 1.0)
    assert first_hard_freeze(daily, date(2026, 9, 20)) is None


def test_hard_freeze_forces_the_season_shut():
    daily = series(date(2026, 9, 1), 40, tmin=8.0, tmax=15.0)
    daily[19] = DailyWeather(date(2026, 9, 20), -8.0, -1.0)
    p = predict_cell(
        cell_id="52.25,21.25", lat=52.25, elevation_m=110,
        daily=daily, today=date(2026, 10, 1),
    )
    assert p.past_peak == "2026-09-25"  # freeze + FREEZE_TO_PAST_PEAK_DAYS
    assert p.state in ("past_peak", "bare")


def test_freeze_never_pushes_the_season_later():
    daily = series(date(2026, 9, 1), 90, tmin=8.0, tmax=15.0)
    daily[80] = DailyWeather(date(2026, 11, 20), -9.0, -2.0)
    p = predict_cell(
        cell_id="x", lat=52.25, elevation_m=110, daily=daily, today=date(2026, 11, 25),
    )
    assert p.past_peak <= "2026-11-04"  # the ordinary window, untouched


# --- state machine --------------------------------------------------------

@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 9, 1), "green"),
        (date(2026, 9, 25), "early"),
        (date(2026, 10, 15), "near_peak"),
        (date(2026, 10, 20), "peak"),
        (date(2026, 10, 30), "past_peak"),
        (date(2026, 11, 20), "bare"),
    ],
)
def test_classify_walks_the_progression(today, expected):
    peak = date(2026, 10, 21)
    assert classify(today, peak, peak - timedelta(days=7), peak + timedelta(days=7)) == expected


def test_advance_state_stops_at_both_ends():
    assert advance_state("green") == "early"
    assert advance_state("bare") == "bare"
    assert advance_state("green", -1) == "green"


# --- NDVI nudge -----------------------------------------------------------

def _near_peak_inputs():
    daily = series(date(2026, 9, 1), 75, tmin=9.0, tmax=16.0)
    return dict(cell_id="52.25,21.25", lat=52.25, elevation_m=110,
                daily=daily, today=date(2026, 10, 15))


def test_ndvi_drop_advances_a_colouring_cell():
    kwargs = _near_peak_inputs()
    assert predict_cell(**kwargs).state == "near_peak"
    assert predict_cell(**kwargs, ndvi_drop=0.40).state == "peak"


def test_small_ndvi_drop_changes_nothing():
    kwargs = _near_peak_inputs()
    assert predict_cell(**kwargs, ndvi_drop=0.05).state == "near_peak"


def test_ndvi_cannot_advance_a_green_cell():
    daily = series(date(2026, 9, 1), 20, tmin=14.0, tmax=22.0)
    p = predict_cell(cell_id="x", lat=45.0, elevation_m=50, daily=daily,
                     today=date(2026, 9, 15), ndvi_drop=0.9)
    assert p.state == "green", "cloud or haze must not fast-forward the whole season"


# --- confidence -----------------------------------------------------------

def test_confidence_scales_with_available_inputs():
    assert confidence_for(have_elevation=True, observed_days=30, have_ndvi=True) == "high"
    assert confidence_for(have_elevation=True, observed_days=30, have_ndvi=False) == "medium"
    assert confidence_for(have_elevation=False, observed_days=30, have_ndvi=False) == "low"
    assert confidence_for(have_elevation=True, observed_days=2, have_ndvi=True) == "low"


def test_extrapolated_baseline_is_never_trusted():
    assert confidence_for(
        have_elevation=True, observed_days=60, have_ndvi=True, extrapolated=True
    ) == "low"


def test_uncovered_peak_costs_one_notch():
    assert confidence_for(
        have_elevation=True, observed_days=30, have_ndvi=True, covers_peak=False
    ) == "medium"


# --- end to end -----------------------------------------------------------

def test_prediction_is_wholly_deterministic():
    kwargs = _near_peak_inputs()
    assert predict_cell(**kwargs).to_json() == predict_cell(**kwargs).to_json()


def test_prediction_shape_matches_the_published_schema():
    p = predict_cell(**_near_peak_inputs()).to_json()
    assert set(p) == {"id", "state", "peak_start", "peak", "past_peak", "confidence", "updated"}
    assert p["peak_start"] < p["peak"] < p["past_peak"]
    assert p["state"] in {"green", "early", "near_peak", "peak", "past_peak", "bare"}
    assert p["confidence"] in {"low", "medium", "high"}


def test_no_weather_at_all_still_produces_a_usable_cell():
    p = predict_cell(cell_id="52.25,21.25", lat=52.25, elevation_m=110,
                     daily=[], today=date(2026, 10, 1))
    assert p.peak == "2026-10-20"  # falls back to pure climatology
    assert p.confidence == "low"
