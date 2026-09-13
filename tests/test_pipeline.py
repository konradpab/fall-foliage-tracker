"""Grid construction, NDVI tile maths, and the runner's output contract."""

import json
from datetime import date

import pytest

from batch import ndvi
from batch.config import PROFILES
from batch.grid import LandMask, build_grid, cell_id
from batch.run import main


# --- grid -----------------------------------------------------------------

def test_land_mask_knows_land_from_sea():
    mask = LandMask.load()
    assert mask.is_land(52.2, 21.0)      # Warsaw
    assert mask.is_land(50.06, 19.94)    # Krakow
    assert not mask.is_land(55.0, 18.5)  # middle of the Baltic
    assert not mask.is_land(42.5, 5.0)   # open Mediterranean


def test_grid_covers_poland_and_skips_open_water():
    cells = build_grid(PROFILES["poland"])
    assert any(abs(c.lat - 52.2) < 0.2 and abs(c.lon - 21.0) < 0.2 for c in cells), "Warsaw"
    assert any(abs(c.lat - 50.06) < 0.2 and abs(c.lon - 19.94) < 0.2 for c in cells), "Krakow"
    assert not any(abs(c.lat - 55.0) < 0.2 and abs(c.lon - 18.5) < 0.2 for c in cells), "Baltic"
    assert 500 < len(cells) < 1500


def test_grid_cells_are_inside_the_profile_bbox():
    p = PROFILES["europe"]
    for c in build_grid(p):
        assert p.lat_min <= c.lat <= p.lat_max
        assert p.lon_min <= c.lon <= p.lon_max


def test_grid_ids_are_unique_and_stable():
    cells = build_grid(PROFILES["dev"])
    ids = [c.id for c in cells]
    assert len(ids) == len(set(ids))
    assert [c.id for c in build_grid(PROFILES["dev"])] == ids


def test_finer_step_yields_more_cells():
    assert len(build_grid(PROFILES["poland"])) > len(build_grid(PROFILES["dev"]))


# --- NDVI tile geometry ---------------------------------------------------

def test_tile_span_halves_each_zoom():
    assert ndvi.tile_span(0) == 180.0
    assert ndvi.tile_span(5) == pytest.approx(5.625)


def test_tile_of_places_warsaw_correctly():
    row, col = ndvi.tile_of(52.25, 21.25, 5)
    assert (row, col) == (int((90 - 52.25) / 5.625), int((21.25 + 180) / 5.625))


def test_pixel_indices_stay_inside_the_tile():
    for lat in (35.0, 52.25, 71.4):
        for lon in (-10.9, 0.0, 21.25, 31.9):
            _, _, py, px = ndvi.pixel_of(lat, lon, 5)
            assert 0 <= py < ndvi.TILE_PX and 0 <= px < ndvi.TILE_PX


def test_pixel_position_moves_the_right_way():
    _, _, py_n, _ = ndvi.pixel_of(52.4, 21.25, 5)
    _, _, py_s, _ = ndvi.pixel_of(52.1, 21.25, 5)
    assert py_n < py_s, "rows increase southwards"


def test_colormap_parsing_skips_nodata_and_transparent_entries():
    xml = """<ColorMaps>
      <ColorMapEntry rgb="0,26,105" transparent="true" value="[-0.3,-0.2)" nodata="true"/>
      <ColorMapEntry rgb="225,225,225" transparent="true" value="[-0.2,-0.1)"/>
      <ColorMapEntry rgb="241,236,236" transparent="false" value="[0.0001,0.0051)"/>
      <ColorMapEntry rgb="0,24,1" transparent="false" value="[0.9901,1.0001)"/>
    </ColorMaps>"""
    cmap = ndvi.parse_colormap(xml)
    assert (0, 26, 105) not in cmap and (225, 225, 225) not in cmap
    assert cmap[(241, 236, 236)] == pytest.approx(0.0026, abs=1e-4)
    assert cmap[(0, 24, 1)] == pytest.approx(0.9951, abs=1e-4)


def test_baseline_date_is_mid_august_of_the_same_season():
    assert ndvi.baseline_date(date(2026, 10, 12)) == date(2026, 8, 15)


# --- runner ---------------------------------------------------------------

def test_offline_run_writes_a_valid_forecast(tmp_path):
    out = tmp_path / "forecast.json"
    assert main(["--offline", "--profile", "dev", "--today", "2026-10-12", "--out", str(out)]) == 0

    payload = json.loads(out.read_text())
    assert payload["version"] == 1
    assert payload["demo"] is True
    assert payload["today"] == "2026-10-12"
    assert payload["sources"]["weather"] == "offline-fixture"
    assert len(payload["bbox"]) == 4 and len(payload["center"]) == 3
    assert payload["cells"], "a run must never emit an empty grid"
    for cell in payload["cells"]:
        assert cell["peak_start"] < cell["peak"] < cell["past_peak"]


def test_offline_run_is_reproducible(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for out in (a, b):
        main(["--offline", "--profile", "dev", "--today", "2026-10-12", "--out", str(out)])
    pa, pb = json.loads(a.read_text()), json.loads(b.read_text())
    assert pa["cells"] == pb["cells"]


def test_live_run_is_not_marked_as_demo(tmp_path, monkeypatch):
    """A network-free 'live' run degrades to climatology, but is not demo data."""
    monkeypatch.setattr("batch.weather.fetch", lambda *a, **k: {})
    monkeypatch.setattr("batch.elevation.fetch_missing", lambda cells, known, **k: known)
    monkeypatch.setattr("batch.ndvi.sample_drop", lambda *a, **k: {})
    out = tmp_path / "f.json"
    assert main(["--profile", "dev", "--today", "2026-10-12", "--no-cache", "--out", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["demo"] is False
    assert payload["sources"]["weather"] == "unavailable"
    assert payload["cells"], "an upstream outage must still produce a file"
