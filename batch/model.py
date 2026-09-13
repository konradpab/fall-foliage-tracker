"""The phenology model: deterministic, rule-based, no ML, no network.

Every function here is pure. `predict_cell` is the only entry point the batch
job needs; everything it depends on is passed in explicitly so the whole model
is testable with fixed inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

from . import config as C

#: Ordered progression. `advance_state` walks one step along this list.
STATES = ["green", "early", "near_peak", "peak", "past_peak", "bare"]


@dataclass(frozen=True)
class DailyWeather:
    """One day of forecast/observed weather for a cell."""

    day: date
    tmin: float | None
    tmax: float | None


@dataclass(frozen=True)
class Prediction:
    id: str
    state: str
    peak_start: str
    peak: str
    past_peak: str
    confidence: str
    updated: str

    def to_json(self) -> dict:
        return asdict(self)


def baseline_peak_doy(lat: float, elevation_m: float | None) -> float:
    """Climatological peak day-of-year from latitude and elevation.

    Later toward the south, earlier with altitude. Constants are documented in
    DECISIONS.md; unknown elevation is treated as sea level.
    """
    elev = 0.0 if elevation_m is None else max(elevation_m, 0.0)
    doy = C.BASELINE_A - C.BASELINE_B_LAT * lat - C.BASELINE_C_ELEV * elev
    return min(max(doy, C.BASELINE_DOY_MIN), C.BASELINE_DOY_MAX)


def season_start(year: int) -> date:
    return date(year, C.SEASON_START_MONTH, C.SEASON_START_DAY)


def weather_shift(
    daily: list[DailyWeather], today: date, window_end: date | None = None
) -> tuple[float, int, int]:
    """Days of advance (negative) or delay (positive) implied by the weather.

    Days from 1 September up to ``window_end`` count. ``window_end`` should be
    the climatological peak: weather only moves a peak that has not happened
    yet, so counting past it would drag the estimate earlier on every cold night
    for the rest of the year. Days beyond the end of the available series simply
    do not count -- which is why the estimate firms up as the peak approaches and
    is stable once the 16-day forecast covers it.
    Returns ``(shift_days, cool_nights, warm_days)``.
    """
    start = season_start(today.year)
    end = window_end if window_end is not None else today
    cool = warm = 0
    for d in daily:
        if d.day < start or d.day > end:
            continue
        if d.tmin is not None and d.tmin < C.COOL_NIGHT_C:
            cool += 1
        if d.tmax is not None and d.tmax > C.WARM_DAY_C:
            warm += 1
    shift = cool * C.COOL_NIGHT_SHIFT + warm * C.WARM_DAY_SHIFT
    return _clamp(shift, -C.MAX_ABS_SHIFT, C.MAX_ABS_SHIFT), cool, warm


def first_hard_freeze(daily: list[DailyWeather], today: date) -> date | None:
    """First day at or before ``today`` with Tmin below the hard-freeze cut."""
    start = season_start(today.year)
    for d in sorted(daily, key=lambda x: x.day):
        if d.day < start or d.day > today:
            continue
        if d.tmin is not None and d.tmin < C.HARD_FREEZE_C:
            return d.day
    return None


def classify(today: date, peak: date, peak_start: date, past_peak: date) -> str:
    """Map today's position in the peak window onto a state."""
    if today < peak_start - timedelta(days=C.EARLY_LEAD_DAYS):
        return "green"
    if today < peak_start:
        return "early"
    if today < peak - timedelta(days=3):
        return "near_peak"
    if today < past_peak:
        return "peak"
    if today < past_peak + timedelta(days=C.BARE_TRAIL_DAYS):
        return "past_peak"
    return "bare"


def advance_state(state: str, steps: int = 1) -> str:
    """Move ``steps`` places along the progression, without falling off the end."""
    i = STATES.index(state)
    return STATES[min(max(i + steps, 0), len(STATES) - 1)]


def confidence_for(
    *,
    have_elevation: bool,
    observed_days: int,
    have_ndvi: bool,
    extrapolated: bool = False,
    covers_peak: bool = True,
) -> str:
    """How much to trust a cell: driven by how much input actually arrived."""
    if observed_days < 7 or extrapolated:
        return "low"
    score = 1 + int(have_elevation) + int(have_ndvi)
    if not covers_peak:
        score -= 1
    return {0: "low", 1: "low", 2: "medium", 3: "high"}[max(score, 0)]


def predict_cell(
    *,
    cell_id: str,
    lat: float,
    elevation_m: float | None,
    daily: list[DailyWeather],
    today: date,
    ndvi_drop: float | None = None,
) -> Prediction:
    """Full prediction for one cell.

    ``ndvi_drop`` is the fractional fall of the latest NDVI composite below the
    cell's August baseline (0.3 == 30% down), or None when unavailable.
    """
    raw_doy = C.BASELINE_A - C.BASELINE_B_LAT * lat - C.BASELINE_C_ELEV * max(elevation_m or 0.0, 0.0)
    base_doy = baseline_peak_doy(lat, elevation_m)
    # Outside the calendar window the linear baseline is extrapolating past the
    # data it was fitted on; say so rather than pretending to the same accuracy.
    clamped = abs(raw_doy - base_doy) > 0.5

    base_peak = date(today.year, 1, 1) + timedelta(days=round(base_doy) - 1)
    shift, _cool, _warm = weather_shift(daily, today, window_end=base_peak)
    peak = date(today.year, 1, 1) + timedelta(days=round(base_doy + shift) - 1)
    peak_start = peak - timedelta(days=C.PEAK_WINDOW_LEAD)
    past_peak = peak + timedelta(days=C.PEAK_WINDOW_TRAIL)

    freeze = first_hard_freeze(daily, today)
    if freeze is not None:
        # A hard freeze ends the season regardless of what the baseline said.
        forced = freeze + timedelta(days=C.FREEZE_TO_PAST_PEAK_DAYS)
        if forced < past_peak:
            past_peak = forced
            peak = min(peak, past_peak - timedelta(days=1))
            peak_start = min(peak_start, peak - timedelta(days=C.PEAK_WINDOW_LEAD))

    state = classify(today, peak, peak_start, past_peak)

    # NDVI is a nudge, never the whole story: it can only ever move a cell one
    # step forward, and only once colouring has plausibly begun.
    if ndvi_drop is not None and ndvi_drop >= C.NDVI_DROP_UPGRADE:
        if state in ("early", "near_peak"):
            state = advance_state(state)

    observed = sum(
        1 for d in daily if season_start(today.year) <= d.day <= today and d.tmin is not None
    )
    # Until the series (observations + 16-day forecast) reaches the peak, part of
    # the window that decides the peak is still unknown.
    covers_peak = any(d.day >= base_peak and d.tmin is not None for d in daily)
    return Prediction(
        id=cell_id,
        state=state,
        peak_start=peak_start.isoformat(),
        peak=peak.isoformat(),
        past_peak=past_peak.isoformat(),
        confidence=confidence_for(
            have_elevation=elevation_m is not None,
            observed_days=observed,
            have_ndvi=ndvi_drop is not None,
            extrapolated=clamped,
            covers_peak=covers_peak,
        ),
        updated=today.isoformat(),
    )


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)
