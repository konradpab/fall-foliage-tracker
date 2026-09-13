"""Daily temperature series per cell, from Open-Meteo.

Open-Meteo is keyless. Requests are batched by coordinate list, retried with
backoff, and cached on disk so re-running the job during development costs
nothing. If the API is unreachable the job does not fail: cells simply come
back with no weather and the model marks them low-confidence.
"""

from __future__ import annotations

import json
import math
import pathlib
import time
from datetime import date, timedelta

from . import config as C
from .grid import Cell
from .model import DailyWeather

CACHE_DIR = pathlib.Path(__file__).with_name(".cache")


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _as_list(payload):
    """Open-Meteo returns an object for one location and a list for many."""
    return payload if isinstance(payload, list) else [payload]


def _parse_location(block: dict) -> list[DailyWeather]:
    daily = block.get("daily") or {}
    days = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    out: list[DailyWeather] = []
    for i, iso in enumerate(days):
        out.append(
            DailyWeather(
                day=date.fromisoformat(iso),
                tmin=_num(tmin[i] if i < len(tmin) else None),
                tmax=_num(tmax[i] if i < len(tmax) else None),
            )
        )
    return out


def _num(v):
    return None if v is None else float(v)


def past_days_needed(today: date) -> int:
    """Days of history back to 1 September, clamped to the API's 92-day window."""
    start = date(today.year, C.SEASON_START_MONTH, C.SEASON_START_DAY)
    if today < start:
        # Before the season starts there is nothing to accumulate.
        return 1
    return min(max((today - start).days + 1, 1), 92)


def fetch(
    cells: list[Cell],
    today: date,
    *,
    cache: bool = True,
    client=None,
) -> dict[str, list[DailyWeather]]:
    """Fetch daily min/max temperature for every cell.

    Returns a mapping of cell id -> daily series. Cells whose request failed are
    absent from the mapping rather than raising.
    """
    import httpx

    key = f"weather-{today.isoformat()}-{len(cells)}"
    cached = _cache_read(key) if cache else None
    if cached is not None:
        return {cid: [DailyWeather(date.fromisoformat(d), t0, t1) for d, t0, t1 in rows]
                for cid, rows in cached.items()}

    owns_client = client is None
    client = client or httpx.Client(
        timeout=60.0, headers={"User-Agent": C.USER_AGENT}, follow_redirects=True
    )
    out: dict[str, list[DailyWeather]] = {}
    try:
        for batch in _chunks(cells, C.WEATHER_BATCH):
            params = {
                "latitude": ",".join(f"{c.lat:.4f}" for c in batch),
                "longitude": ",".join(f"{c.lon:.4f}" for c in batch),
                "daily": "temperature_2m_max,temperature_2m_min",
                "past_days": str(past_days_needed(today)),
                "forecast_days": "16",
                "timezone": "UTC",
            }
            payload = _get_json(client, C.OPEN_METEO_FORECAST, params)
            if payload is None:
                continue
            blocks = _as_list(payload)
            for cell, block in zip(batch, blocks):
                series = _parse_location(block)
                if series:
                    out[cell.id] = series
    finally:
        if owns_client:
            client.close()

    if cache and out:
        _cache_write(
            key,
            {cid: [[d.day.isoformat(), d.tmin, d.tmax] for d in rows] for cid, rows in out.items()},
        )
    return out


def _get_json(client, url: str, params: dict, attempts: int = 3):
    for attempt in range(attempts):
        try:
            r = client.get(url, params=params)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the job
            if attempt == attempts - 1:
                print(f"  ! {url} failed after {attempts} attempts: {exc}")
                return None
            time.sleep(2 ** attempt)
    return None


# --- offline mode ---------------------------------------------------------

def synthetic(cells: list[Cell], today: date) -> dict[str, list[DailyWeather]]:
    """Deterministic climatological stand-in used by ``run.py --offline``.

    This is a smooth seasonal curve, NOT a weather observation. It exists so the
    pipeline, the tests and the demo build run without network access. Output
    generated this way is tagged ``source: "offline-fixture"`` and the UI labels
    it as demo data.
    """
    out: dict[str, list[DailyWeather]] = {}
    start = date(today.year, C.SEASON_START_MONTH, 1) - timedelta(days=10)
    for cell in cells:
        rows: list[DailyWeather] = []
        # Warmer to the south and to the west; colder with a continental interior.
        mean = 22.0 - 0.55 * (cell.lat - 40.0) + 0.03 * (cell.lon - 10.0)
        for i in range(120):
            day = start + timedelta(days=i)
            doy = day.timetuple().tm_yday
            seasonal = 9.0 * math.cos((doy - 200) / 365.0 * 2 * math.pi)
            wobble = 1.8 * math.sin(i / 5.0 + cell.lat)
            t = mean + seasonal - 2.5 + wobble
            rows.append(DailyWeather(day=day, tmin=round(t - 6.5, 1), tmax=round(t + 5.5, 1)))
        out[cell.id] = rows
    return out


# --- tiny disk cache ------------------------------------------------------

def _cache_path(key: str) -> pathlib.Path:
    return CACHE_DIR / f"{key}.json"


def _cache_read(key: str):
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def _cache_write(key: str, value) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    _cache_path(key).write_text(json.dumps(value))
