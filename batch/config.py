"""Static configuration for the foliage batch job.

Everything tunable lives here so that changing the region, the grid resolution
or the phenology constants is a one-file edit. See DECISIONS.md for how the
constants were derived.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """A region + resolution the batch job can be run for."""

    name: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    step: float
    #: Map view the client opens on: (lon, lat, zoom).
    center: tuple[float, float, float]

    def cell_count_estimate(self) -> int:
        rows = round((self.lat_max - self.lat_min) / self.step)
        cols = round((self.lon_max - self.lon_min) / self.step)
        return rows * cols


#: Default view is Poland; the default *data extent* is the whole of Europe so
#: that any European country works out of the box.
POLAND_CENTER = (19.4, 52.0, 5.0)

PROFILES: dict[str, Profile] = {
    # ~2.9k land cells. Comfortably inside Open-Meteo's free-tier budget.
    "europe": Profile(
        name="europe",
        lat_min=35.0,
        lat_max=71.5,
        lon_min=-11.0,
        lon_max=32.0,
        step=0.5,
        center=POLAND_CENTER,
    ),
    # ~1.0k land cells at double the resolution, for a Poland-only deployment.
    "poland": Profile(
        name="poland",
        lat_min=48.75,
        lat_max=55.0,
        lon_min=13.5,
        lon_max=24.5,
        step=0.25,
        center=(19.4, 52.0, 6.0),
    ),
    # Small, fast profile used by the test-suite and by `--profile dev`.
    "dev": Profile(
        name="dev",
        lat_min=49.0,
        lat_max=54.5,
        lon_min=14.5,
        lon_max=24.0,
        step=1.0,
        center=POLAND_CENTER,
    ),
}

DEFAULT_PROFILE = "europe"

# --- Phenology model constants -------------------------------------------
# baseline_doy = A - B * latitude_deg - C * elevation_m
BASELINE_A = 414.1
BASELINE_B_LAT = 2.30
BASELINE_C_ELEV = 0.010
#: Baseline is clamped to a sane calendar window (mid-Aug .. early Dec).
BASELINE_DOY_MIN = 228
BASELINE_DOY_MAX = 340

#: Season accumulation starts on this month/day.
SEASON_START_MONTH = 9
SEASON_START_DAY = 1

COOL_NIGHT_C = 7.0        # Tmin below this advances colouring
WARM_DAY_C = 27.0         # Tmax above this delays colouring
HARD_FREEZE_C = -2.0      # Tmin below this strips leaves
COOL_NIGHT_SHIFT = -0.6   # days of advance per cool night
WARM_DAY_SHIFT = 0.5      # days of delay per warm day
MAX_ABS_SHIFT = 14.0      # total weather shift is capped at +/- this
FREEZE_TO_PAST_PEAK_DAYS = 5

PEAK_WINDOW_LEAD = 7      # peak_start = peak - this
PEAK_WINDOW_TRAIL = 7     # past_peak  = peak + this
EARLY_LEAD_DAYS = 21      # "early" begins this many days before peak_start
BARE_TRAIL_DAYS = 14      # "bare" begins this many days after past_peak

#: NDVI must fall at least this fraction below its August baseline before it is
#: allowed to nudge a cell forward one state.
NDVI_DROP_UPGRADE = 0.25

# --- Data sources ---------------------------------------------------------
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"
#: Locations per Open-Meteo request. Kept well under the documented limits so
#: a single failure never costs much work.
WEATHER_BATCH = 50
ELEVATION_BATCH = 100

GIBS_WMTS_4326 = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/"
    "{layer}/default/{date}/{tms}/{z}/{row}/{col}.png"
)
NDVI_LAYER = "MODIS_Terra_NDVI_8Day"
NDVI_TMS = "250m"
#: Zoom level used for NDVI sampling. z=5 in the GIBS 4326 grid is ~2 km/px,
#: far finer than the 0.5 deg forecast cell, and keeps the tile count small.
NDVI_ZOOM = 5

USER_AGENT = "fall-foliage-tracker/1.0 (+https://github.com/konradpab/fall-foliage-tracker)"
