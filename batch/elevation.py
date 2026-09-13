"""Per-cell elevation from Open-Meteo's keyless elevation API.

Elevation never changes, so the result is written to ``public/data/grid.json``
and committed. Subsequent runs read that file and only ask the API about cells
they have not seen before, which is normally none.
"""

from __future__ import annotations

import json
import pathlib
import time

from . import config as C
from .grid import Cell


def load_cache(path: pathlib.Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {k: float(v) for k, v in (data.get("elevation") or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def save_cache(path: pathlib.Path, elevations: dict[str, float], profile_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"profile": profile_name, "elevation": {k: round(v, 1) for k, v in elevations.items()}})
    )


def fetch_missing(
    cells: list[Cell],
    known: dict[str, float],
    *,
    client=None,
) -> dict[str, float]:
    """Fill in elevations for cells missing from ``known``. Never raises."""
    import httpx

    missing = [c for c in cells if c.id not in known]
    if not missing:
        return known
    print(f"  elevation: fetching {len(missing)} new cells")

    owns_client = client is None
    client = client or httpx.Client(
        timeout=60.0, headers={"User-Agent": C.USER_AGENT}, follow_redirects=True
    )
    out = dict(known)
    try:
        for i in range(0, len(missing), C.ELEVATION_BATCH):
            batch = missing[i : i + C.ELEVATION_BATCH]
            params = {
                "latitude": ",".join(f"{c.lat:.4f}" for c in batch),
                "longitude": ",".join(f"{c.lon:.4f}" for c in batch),
            }
            try:
                r = client.get(C.OPEN_METEO_ELEVATION, params=params)
                r.raise_for_status()
                values = r.json().get("elevation") or []
            except Exception as exc:  # noqa: BLE001
                print(f"  ! elevation batch failed: {exc}")
                continue
            for cell, v in zip(batch, values):
                if v is not None:
                    out[cell.id] = float(v)
            time.sleep(0.2)
    finally:
        if owns_client:
            client.close()
    return out
