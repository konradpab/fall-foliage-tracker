"""Optional NDVI sampling from NASA GIBS.

This module is entirely best-effort. It is the only part of the pipeline that
is allowed to be unavailable: if Pillow is not installed, if a tile 404s, or if
GIBS is down, `sample_drop` returns an empty mapping and the run continues with
weather-only predictions at a lower confidence.

How it works: GIBS serves NDVI as a colourised PNG, so we fetch the published
colour map, invert it (every entry has a unique RGB triple), and read NDVI back
out of the pixels. We compare the most recent composite against a mid-August
baseline and report the fractional drop per forecast cell.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from . import config as C
from .grid import Cell

COLORMAP_URL = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml"
TILE_PX = 512
#: NDVI below this is bare ground / water / cloud - not a leaf-off signal.
MIN_VEGETATED = 0.20


def available() -> bool:
    """True when the optional imaging dependency is installed."""
    try:
        import PIL  # noqa: F401
        import numpy  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


# --- tile geometry (GIBS EPSG:4326 grid) ---------------------------------

def tile_span(zoom: int) -> float:
    """Degrees covered by one tile edge at ``zoom``."""
    return 360.0 / (2 * 2 ** zoom)


def tile_of(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    span = tile_span(zoom)
    col = int((lon + 180.0) / span)
    row = int((90.0 - lat) / span)
    return row, col


def pixel_of(lat: float, lon: float, zoom: int) -> tuple[int, int, int, int]:
    """Return ``(row, col, py, px)`` for a coordinate."""
    span = tile_span(zoom)
    row, col = tile_of(lat, lon, zoom)
    lon0 = -180.0 + col * span
    lat1 = 90.0 - row * span
    px = min(int((lon - lon0) / span * TILE_PX), TILE_PX - 1)
    py = min(int((lat1 - lat) / span * TILE_PX), TILE_PX - 1)
    return row, col, py, px


# --- colour map -----------------------------------------------------------

_INTERVAL = re.compile(r"\[?\(?\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)")


def parse_colormap(xml_text: str) -> dict[tuple[int, int, int], float]:
    """RGB triple -> NDVI midpoint, skipping nodata/transparent entries."""
    out: dict[tuple[int, int, int], float] = {}
    root = ET.fromstring(xml_text)
    for entry in root.iter("ColorMapEntry"):
        if entry.get("nodata") == "true" or entry.get("transparent") == "true":
            continue
        rgb = entry.get("rgb")
        value = entry.get("value")
        if not rgb or not value:
            continue
        m = _INTERVAL.match(value)
        if not m:
            continue
        lo, hi = float(m.group(1)), float(m.group(2))
        try:
            r, g, b = (int(x) for x in rgb.split(",")[:3])
        except ValueError:
            continue
        out[(r, g, b)] = (lo + hi) / 2.0
    return out


def latest_composite_date(today: date, lag_days: int = 3) -> date:
    """MOD13Q4N is a daily rolling 8-day product; back off for ingest latency."""
    return today - timedelta(days=lag_days)


def baseline_date(today: date) -> date:
    """Mid-August of the current season, the 'fully green' reference."""
    return date(today.year, 8, 15)


# --- sampling -------------------------------------------------------------

def sample_drop(
    cells: list[Cell],
    today: date,
    *,
    zoom: int | None = None,
    client=None,
    max_date_retries: int = 6,
) -> dict[str, float]:
    """Fractional NDVI drop below the August baseline, per cell id.

    Returns ``{}`` on any failure. Values are clipped to ``[0, 1]``; cells whose
    August baseline was not vegetated are omitted.
    """
    if not available():
        print("  ndvi: Pillow/numpy not installed - skipping (optional)")
        return {}

    import httpx
    import numpy as np

    zoom = C.NDVI_ZOOM if zoom is None else zoom
    owns_client = client is None
    client = client or httpx.Client(
        timeout=60.0, headers={"User-Agent": C.USER_AGENT}, follow_redirects=True
    )
    try:
        try:
            r = client.get(COLORMAP_URL)
            r.raise_for_status()
            cmap = parse_colormap(r.text)
        except Exception as exc:  # noqa: BLE001
            print(f"  ndvi: colour map unavailable ({exc}) - skipping")
            return {}
        if not cmap:
            return {}

        keys = np.array(list(cmap.keys()), dtype=np.int16)
        vals = np.array(list(cmap.values()), dtype=np.float32)

        needed = sorted({tile_of(c.lat, c.lon, zoom) for c in cells})
        current = _load_tiles(client, needed, latest_composite_date(today), zoom,
                              keys, vals, np, max_date_retries)
        if not current:
            print("  ndvi: no current tiles available - skipping")
            return {}
        base = _load_tiles(client, needed, baseline_date(today), zoom,
                           keys, vals, np, max_date_retries)
        if not base:
            print("  ndvi: no baseline tiles available - skipping")
            return {}

        out: dict[str, float] = {}
        for cell in cells:
            row, col, py, px = pixel_of(cell.lat, cell.lon, zoom)
            cur_t, base_t = current.get((row, col)), base.get((row, col))
            if cur_t is None or base_t is None:
                continue
            b = float(base_t[py, px])
            c_ = float(cur_t[py, px])
            if not (b == b) or not (c_ == c_) or b < MIN_VEGETATED:
                continue
            out[cell.id] = max(0.0, min(1.0, (b - c_) / b))
        print(f"  ndvi: sampled {len(out)}/{len(cells)} cells")
        return out
    finally:
        if owns_client:
            client.close()


def _load_tiles(client, needed, when: date, zoom, keys, vals, np, max_date_retries):
    """Fetch and decode every needed tile for ``when``, walking back on failure."""
    from PIL import Image

    for back in range(max_date_retries):
        day = when - timedelta(days=back)
        tiles: dict[tuple[int, int], object] = {}
        failures = 0
        for row, col in needed:
            url = C.GIBS_WMTS_4326.format(
                layer=C.NDVI_LAYER, date=day.isoformat(), tms=C.NDVI_TMS,
                z=zoom, row=row, col=col,
            )
            try:
                r = client.get(url)
                if r.status_code != 200:
                    failures += 1
                    continue
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                arr = np.asarray(img, dtype=np.int16)
                tiles[(row, col)] = _decode(arr, keys, vals, np)
            except Exception:  # noqa: BLE001
                failures += 1
        if tiles and failures <= len(needed) // 2:
            return tiles
    return {}


def _decode(arr, keys, vals, np):
    """Map an RGB tile to NDVI by nearest palette colour, on unique colours only."""
    flat = arr.reshape(-1, 3)
    uniq, inverse = np.unique(flat, axis=0, return_inverse=True)
    d = np.abs(uniq[:, None, :].astype(np.int32) - keys[None, :, :].astype(np.int32)).sum(axis=2)
    nearest = d.argmin(axis=1)
    # Colours far from every palette entry are land-mask / fill, not NDVI.
    lut = np.where(d[np.arange(len(uniq)), nearest] <= 12, vals[nearest], np.nan)
    return lut[inverse].reshape(arr.shape[0], arr.shape[1])
