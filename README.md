# Fall Foliage Tracker — Europe

Where the leaves are turning across Europe, and when each region is expected to
peak. Open the page, tap the map, get an answer.

No accounts. No cookies. No server. No API keys. Runs on free static hosting for
**€0/month**.

> **Live:** https://konradpab.github.io/fall-foliage-tracker/
> *(replace `konradpab` after you fork — see [Deploying](#deploying))*

---

## What it does

- **Current state** for any point on land in Europe — one of *still green →
  early colour → near peak → peak → past peak → bare*.
- **Forecast peak window** — a start date, a peak date and a past-peak date per
  grid cell, refreshed nightly.
- **Satellite overlays** — NASA true-colour and NDVI vegetation imagery, with a
  30-day date slider, straight from NASA GIBS.
- **Nearby live views** — public webcams near the selected point, when a
  community-maintained list or a Windy API key supplies them.

The default map view is **Poland**; the data covers Europe from Andalusia to
Lapland, so any European country works out of the box.

## How the forecast works

A deliberately simple, deterministic, rule-based model. No machine learning, no
training pipeline, nothing to retrain when it drifts. Every step is a pure
function in [`batch/model.py`](batch/model.py) and is unit-tested.

**1. Climatological baseline.** Each 0.5° cell gets a starting peak date from
its latitude and elevation:

```
baseline_doy = 414.1 − 2.30 × latitude° − 0.010 × elevation_m
```

Colour arrives later toward the south (about 2.3 days per degree of latitude)
and earlier with altitude (about 10 days per 1000 m). Warsaw (52.25 °N, 110 m)
comes out at 20 October; Lapland at early September; the Po valley in November.

**2. Weather adjustment.** Daily minimum and maximum temperatures from
1 September onward move that date:

| Condition | Effect |
| --- | --- |
| Night with Tmin < 7 °C | −0.6 days (earlier) |
| Day with Tmax > 27 °C | +0.5 days (later) |
| Total shift | capped at ±14 days |
| Night with Tmin < −2 °C | hard freeze: past peak within 5 days |

Only days up to the **climatological peak** count. Weather after the peak
cannot retroactively move it, which is what keeps the published date stable
instead of sliding earlier on every cold night for the rest of the year. The
estimate firms up as the 16-day forecast reaches the peak window.

**3. NDVI check (optional).** The latest MODIS 8-day NDVI composite is compared
against a mid-August baseline for the same cell. A drop of 25% or more nudges a
cell one step further along — but only a cell that is already colouring, so a
cloudy tile can never fast-forward the whole season. If NASA GIBS is
unreachable, this step is skipped and the forecast is weather-only.

**4. Confidence** reports how much of the above actually arrived: `high` needs
elevation, a full weather series covering the peak, and NDVI. Cells whose
baseline hits the calendar clamp — mostly the Mediterranean, where the model is
weakest — are always `low`.

### What it is not

It is a rule-based guess at a regional average, not an observation of your
local trees. Species mix matters enormously and the model knows nothing about
it: a beech wood and an oak wood in the same cell peak weeks apart. Around the
Mediterranean, where much of the canopy is evergreen, treat the output as
decorative. Expect ±5 days at best in Central Europe, worse elsewhere.

## Architecture

```
Nightly GitHub Action ─→ batch/ (Python) ─→ public/data/forecast.json ─→ commit
                                                                          │
                          GitHub Pages ←─ vite build ←──────────────────── ┘
                                │
                          Browser: one fetch, then everything is local
```

The client downloads **one** JSON file (≈13 kB gzipped) and does nearest-cell
lookups in memory. Clicking the map makes no network request. The only runtime
calls are map tiles, optional satellite tiles, and an optional throttled
geocoding request for the place name.

If the nightly job fails, the previous `forecast.json` stays live and the UI
shows how many days old it is. If any single source is down, a chip says so and
the rest keeps working.

```
.github/workflows/
  nightly.yml            cron 06:00 UTC: rebuild data, sanity-check, commit
  deploy.yml             test + build + publish to Pages on push to main
batch/
  config.py              profiles, model constants, endpoints — all tunables
  grid.py                land grid from a bundled 0.25° land mask
  weather.py             Open-Meteo pulls, batched, cached, retried
  elevation.py           one-time elevation lookup, cached in the repo
  model.py               the phenology rules (pure functions)
  ndvi.py                optional NDVI sampling from NASA GIBS
  run.py                 entry point
  data/landmask.json     4.7 kB packed land/water bitmask for Europe
public/data/
  forecast.json          the nightly output (committed)
  grid.json              per-cell elevation cache (committed)
  webcams.json           community-maintained webcam list
src/
  forecast.ts            data loading + nearest-cell index
  map.ts                 MapLibre, choropleth, GIBS overlays
  panel.ts               detail panel and peak-window timeline
  layers.ts              GIBS layer definitions and tile URLs
  search.ts              Nominatim search and reverse geocoding, throttled
  webcams.ts             local list + optional Windy plugin
tests/                   pytest — model and pipeline
src/forecast.test.ts     vitest — lookup, dates, tile maths
```

## Running locally

You need Python 3.11+ and Node 20+.

```bash
git clone https://github.com/konradpab/fall-foliage-tracker
cd fall-foliage-tracker

# 1. Data. --offline needs no network and writes clearly-marked demo data.
pip install -r requirements.txt
python -m batch.run --offline

# 2. App.
npm install
npm run dev          # http://localhost:5173
```

For real data, drop `--offline`. A full `europe` run takes a few minutes and
makes about 70 Open-Meteo requests, comfortably inside the free tier.

```bash
python -m batch.run                       # europe, 0.5°, ~3300 cells
python -m batch.run --profile poland      # Poland only, 0.25°, ~1000 cells
python -m batch.run --no-ndvi             # skip satellite sampling
python -m batch.run --today 2026-10-12    # pretend it is a different day
```

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest     # 46 tests: model, grid, tile maths, runner contract
npm test             # 18 tests: lookup, dates, GIBS urls, webcam proximity
npm run build && npm run size   # typecheck, build, payload budgets
```

### Checking the upstream services

Upstream layers get renamed and tile-matrix-sets get retired without notice,
and the failure mode is a silent HTTP 400. When something looks wrong, ask:

```bash
python -m batch.scripts.verify_endpoints
```

It reports each endpoint, and exits non-zero only if a *required* one is down —
NDVI and the colour map are optional by design.

## Deploying

1. Fork or create the repo, push to `main`.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Settings → Actions → General → Workflow permissions: Read and write.**
   The nightly job commits the data file back to the repo.
4. Push. `deploy.yml` runs the tests, builds, and publishes.
5. Run **Actions → Nightly forecast → Run workflow** once to replace the demo
   data with a real run.

Replace `konradpab` in this README, in `index.html`'s footer link and in
`batch/config.py`'s `USER_AGENT` with your GitHub username. Nominatim's usage
policy asks for a contactable identifier, so this matters.

**Custom domain or Cloudflare Pages:** set the repository variable
`BASE_PATH=/`. For Cloudflare Pages, build with `npm run build` and publish
`dist`; the nightly job still runs on GitHub Actions.

## Configuration

### Change the region or resolution

Everything lives in [`batch/config.py`](batch/config.py). Add a profile:

```python
"iberia": Profile(
    name="iberia",
    lat_min=36.0, lat_max=44.0,
    lon_min=-10.0, lon_max=3.5,
    step=0.25,
    center=(-3.7, 40.4, 6.0),   # lon, lat, zoom
),
```

Then `python -m batch.run --profile iberia`. The client reads the bounding box,
step and centre out of `forecast.json`, so nothing on the front end changes.

The bundled land mask covers 34–72 °N, 12 °W–34 °E. Outside it every cell is
treated as land; to go further afield, regenerate it:

```bash
pip install global-land-mask
python batch/scripts/gen_landmask.py     # after editing the bbox at the top
```

Keep an eye on the size: cells scale with the inverse square of the step, and
so does the number of Open-Meteo requests.

### Add a webcam

Edit [`public/data/webcams.json`](public/data/webcams.json) and open a pull
request. See [CONTRIBUTING.md](CONTRIBUTING.md) for the rules — briefly: it must
be publicly accessible, need no login or key, and be something the operator
publishes deliberately.

```json
{ "id": "zakopane-gubalowka", "title": "Zakopane — Gubałówka",
  "lat": 49.30, "lon": 19.94, "kind": "page",
  "url": "https://example.org/webcam", "source": "Example Park Authority" }
```

`kind` is `page` (a link), `image` (a still that refreshes), `mjpeg` or `hls`.

### Windy webcams (optional)

Set the repository secret `WINDY_API_KEY`. Without it the panel simply hides
itself and no request is made. This is the one feature that needs a key, which
is why it is a plugin rather than part of the core path.

## Cost

**€0.** GitHub Pages and Actions are free for public repositories; Open-Meteo,
NASA GIBS, OpenFreeMap and Nominatim are all free and keyless for this volume.
There is no database and nothing to keep running.

## Data sources & attribution

- Weather — [Open-Meteo](https://open-meteo.com/) (CC BY 4.0)
- Elevation — Open-Meteo Elevation API (Copernicus DEM)
- Imagery — [NASA EOSDIS GIBS](https://earthdata.nasa.gov/gibs)
- Basemap — [OpenFreeMap](https://openfreemap.org/), data ©
  [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL)
- Search — [Nominatim](https://nominatim.org/) (ODbL)
- Rendering — [MapLibre GL JS](https://maplibre.org/)
- Land mask — [global-land-mask](https://pypi.org/project/global-land-mask/),
  build-time only

## Licence

[MIT](LICENSE). Data from the sources above carries its own licence, listed
above and in the app footer.
