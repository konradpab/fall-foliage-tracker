"""Nightly batch entry point.

    python -m batch.run                  # live run, default (europe) profile
    python -m batch.run --profile poland # higher-resolution Poland-only grid
    python -m batch.run --offline        # no network; writes clearly-marked demo data

Writes ``public/data/forecast.json``. On any partial failure it writes what it
has and exits 0, so a flaky upstream never replaces good data with nothing --
the previous file simply stays live and the UI ages it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import date, datetime, timezone

from . import elevation as elev_mod
from . import ndvi as ndvi_mod
from . import weather as weather_mod
from .config import DEFAULT_PROFILE, PROFILES
from .grid import build_grid
from .model import predict_cell

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "public" / "data"
FORECAST_PATH = DATA_DIR / "forecast.json"
GRID_PATH = DATA_DIR / "grid.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build the foliage forecast.")
    p.add_argument("--profile", default=DEFAULT_PROFILE, choices=sorted(PROFILES))
    p.add_argument("--offline", action="store_true",
                   help="Skip all network calls and emit demo data.")
    p.add_argument("--no-ndvi", action="store_true", help="Skip NDVI sampling.")
    p.add_argument("--no-cache", action="store_true", help="Ignore the on-disk weather cache.")
    p.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD), for testing.")
    p.add_argument("--out", default=None, help="Override the output path.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile = PROFILES[args.profile]
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    out_path = pathlib.Path(args.out) if args.out else FORECAST_PATH

    print(f"profile={profile.name} step={profile.step} today={today} offline={args.offline}")

    cells = build_grid(profile)
    print(f"  grid: {len(cells)} land cells")
    if not cells:
        print("  ! empty grid - check the profile bbox", file=sys.stderr)
        return 1

    sources: dict[str, str] = {}

    # --- elevation (cached in the repo; effectively a one-time cost) -------
    known = elev_mod.load_cache(GRID_PATH)
    if args.offline:
        elevations = known
        sources["elevation"] = "cache" if known else "unavailable"
    else:
        elevations = elev_mod.fetch_missing(cells, known)
        if elevations:
            elev_mod.save_cache(GRID_PATH, elevations, profile.name)
        sources["elevation"] = "open-meteo" if elevations else "unavailable"
    cells = [c.__class__(c.id, c.lat, c.lon, elevations.get(c.id)) for c in cells]

    # --- weather ----------------------------------------------------------
    if args.offline:
        wx = weather_mod.synthetic(cells, today)
        sources["weather"] = "offline-fixture"
    else:
        wx = weather_mod.fetch(cells, today, cache=not args.no_cache)
        sources["weather"] = "open-meteo" if wx else "unavailable"
    print(f"  weather: {len(wx)}/{len(cells)} cells")

    # --- NDVI (optional) --------------------------------------------------
    drops: dict[str, float] = {}
    if args.offline or args.no_ndvi:
        sources["ndvi"] = "skipped"
    else:
        drops = ndvi_mod.sample_drop(cells, today)
        sources["ndvi"] = "nasa-gibs" if drops else "unavailable"

    # --- model ------------------------------------------------------------
    predictions = [
        predict_cell(
            cell_id=c.id,
            lat=c.lat,
            elevation_m=c.elevation,
            daily=wx.get(c.id, []),
            today=today,
            ndvi_drop=drops.get(c.id),
        ).to_json()
        for c in cells
    ]

    payload = {
        "version": 1,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "profile": profile.name,
        "step": profile.step,
        "bbox": [profile.lon_min, profile.lat_min, profile.lon_max, profile.lat_max],
        "center": list(profile.center),
        "demo": bool(args.offline),
        "sources": sources,
        "cells": predictions,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    size = out_path.stat().st_size
    print(f"  wrote {out_path.relative_to(ROOT) if out_path.is_relative_to(ROOT) else out_path}"
          f" ({size / 1024:.0f} kB raw, {len(predictions)} cells)")
    _summarise(predictions)
    return 0


def _summarise(predictions: list[dict]) -> None:
    counts: dict[str, int] = {}
    for p in predictions:
        counts[p["state"]] = counts.get(p["state"], 0) + 1
    print("  states: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    raise SystemExit(main())
