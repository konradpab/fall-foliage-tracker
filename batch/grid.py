"""Build the forecast grid for a profile.

The grid is every cell centre inside the profile's bounding box whose centre
falls on land, according to the bundled 0.25 degree land mask. The mask is
sampled by nearest cell, so the grid step is independent of the mask step.
"""

from __future__ import annotations

import base64
import json
import pathlib
from dataclasses import dataclass

from .config import Profile

_MASK_PATH = pathlib.Path(__file__).with_name("data") / "landmask.json"


@dataclass(frozen=True)
class Cell:
    id: str
    lat: float
    lon: float
    elevation: float | None = None


class LandMask:
    """A packed bit-per-cell land/water mask over a fixed bounding box."""

    def __init__(self, meta: dict) -> None:
        self.lat0 = float(meta["lat0"])
        self.lon0 = float(meta["lon0"])
        self.lat1 = float(meta["lat1"])
        self.lon1 = float(meta["lon1"])
        self.step = float(meta["step"])
        self.rows = int(meta["rows"])
        self.cols = int(meta["cols"])
        self.bits = base64.b64decode(meta["bits_b64"])

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> "LandMask":
        return cls(json.loads((path or _MASK_PATH).read_text()))

    def is_land(self, lat: float, lon: float) -> bool:
        if not (self.lat0 <= lat < self.lat1 and self.lon0 <= lon < self.lon1):
            # Outside the mask we cannot tell; assume land so that widening the
            # bbox degrades into "a few sea cells" rather than an empty grid.
            return True
        r = int((lat - self.lat0) / self.step)
        c = int((lon - self.lon0) / self.step)
        r = min(max(r, 0), self.rows - 1)
        c = min(max(c, 0), self.cols - 1)
        i = r * self.cols + c
        return bool(self.bits[i >> 3] & (1 << (i & 7)))


def cell_id(lat: float, lon: float) -> str:
    """Stable identifier for a cell centre, e.g. ``"52.25,21.25"``."""
    return f"{lat:.2f},{lon:.2f}"


def build_grid(profile: Profile, mask: LandMask | None = None) -> list[Cell]:
    """Return the land cells of ``profile``, ordered south-to-north."""
    mask = mask or LandMask.load()
    cells: list[Cell] = []
    rows = round((profile.lat_max - profile.lat_min) / profile.step)
    cols = round((profile.lon_max - profile.lon_min) / profile.step)
    for r in range(rows):
        lat = round(profile.lat_min + (r + 0.5) * profile.step, 4)
        for c in range(cols):
            lon = round(profile.lon_min + (c + 0.5) * profile.step, 4)
            if mask.is_land(lat, lon):
                cells.append(Cell(id=cell_id(lat, lon), lat=lat, lon=lon))
    return cells
