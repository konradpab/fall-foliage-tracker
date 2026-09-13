"""Check that every upstream endpoint still answers the way we expect.

    python -m batch.scripts.verify_endpoints

Upstream services rename layers and retire tile-matrix-sets without notice, and
the failure mode is a silent HTTP 400 that looks exactly like "this layer does
not exist" (see DECISIONS.md). Run this when something looks wrong, or on a
schedule, rather than guessing.

Exits non-zero if anything required is broken. NDVI and the colour map are
reported but not fatal: the app is designed to run without them.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from .. import config as C
from ..ndvi import COLORMAP_URL, parse_colormap


def main() -> int:
    import httpx

    today = date.today()
    client = httpx.Client(timeout=30.0, headers={"User-Agent": C.USER_AGENT},
                          follow_redirects=True)
    failures: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, detail: str, *, required: bool) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:<46} {detail}")
        if not ok:
            (failures if required else warnings).append(name)

    print("Open-Meteo")
    try:
        r = client.get(C.OPEN_METEO_FORECAST, params={
            "latitude": "52.25,50.06", "longitude": "21.25,19.94",
            "daily": "temperature_2m_max,temperature_2m_min",
            "past_days": "5", "forecast_days": "16", "timezone": "UTC",
        })
        payload = r.json()
        blocks = payload if isinstance(payload, list) else [payload]
        days = len(blocks[0].get("daily", {}).get("time", []))
        check("forecast (2 coords)", r.status_code == 200 and len(blocks) == 2 and days >= 20,
              f"HTTP {r.status_code}, {len(blocks)} blocks, {days} days", required=True)
    except Exception as exc:  # noqa: BLE001
        check("forecast (2 coords)", False, str(exc)[:60], required=True)

    try:
        r = client.get(C.OPEN_METEO_ELEVATION,
                       params={"latitude": "52.25,50.06", "longitude": "21.25,19.94"})
        elev = r.json().get("elevation", [])
        check("elevation", r.status_code == 200 and len(elev) == 2,
              f"HTTP {r.status_code}, {elev}", required=True)
    except Exception as exc:  # noqa: BLE001
        check("elevation", False, str(exc)[:60], required=True)

    print("\nNASA GIBS tiles")
    # A tile over central Europe at each layer's documented matrix set.
    tiles = [
        ("truecolor 3857", "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
         f"VIIRS_SNPP_CorrectedReflectance_TrueColor/default/"
         f"{(today - timedelta(days=2)).isoformat()}/GoogleMapsCompatible_Level9/5/10/17.jpg",
         True),
        ("ndvi 3857 (Level9)", "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
         f"{C.NDVI_LAYER}/default/{(today - timedelta(days=4)).isoformat()}/"
         "GoogleMapsCompatible_Level9/5/10/17.png", False),
        ("ndvi 4326 (250m)", C.GIBS_WMTS_4326.format(
            layer=C.NDVI_LAYER, date=(today - timedelta(days=4)).isoformat(),
            tms=C.NDVI_TMS, z=C.NDVI_ZOOM, row=6, col=35), False),
    ]
    for name, url, required in tiles:
        try:
            r = client.get(url)
            ok = r.status_code == 200 and len(r.content) > 500
            check(name, ok, f"HTTP {r.status_code}, {len(r.content)} bytes", required=required)
        except Exception as exc:  # noqa: BLE001
            check(name, False, str(exc)[:60], required=required)

    print("\nNASA GIBS colour map")
    try:
        r = client.get(COLORMAP_URL)
        cmap = parse_colormap(r.text) if r.status_code == 200 else {}
        check("MODIS_NDVI.xml", len(cmap) > 50, f"{len(cmap)} usable entries", required=False)
    except Exception as exc:  # noqa: BLE001
        check("MODIS_NDVI.xml", False, str(exc)[:60], required=False)

    print("\nBasemap")
    try:
        r = client.get("https://tiles.openfreemap.org/styles/positron")
        style = r.json() if r.status_code == 200 else {}
        check("OpenFreeMap positron style", bool(style.get("sources")),
              f"HTTP {r.status_code}, {len(style.get('layers', []))} layers", required=True)
    except Exception as exc:  # noqa: BLE001
        check("OpenFreeMap positron style", False, str(exc)[:60], required=True)

    client.close()

    print()
    if warnings:
        print(f"optional sources unavailable: {', '.join(warnings)}")
        print("  (the app degrades to weather-only forecasts and shows a chip)")
    if failures:
        print(f"REQUIRED sources broken: {', '.join(failures)}")
        return 1
    print("all required endpoints healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
