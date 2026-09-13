# Decisions, assumptions and endpoint verification

Everything here was decided while building, not planned in advance. Where a
brief could not be met as written, that is stated plainly rather than papered
over.

## 1. Endpoints: what was verified, and how

Verified live from the build environment on **5 September 2026**. Anything that
could not be verified is marked as such — being honest about that is more
useful than a checklist of ticks.

| Endpoint | Status | Notes |
| --- | --- | --- |
| `gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg` | **verified** | Returns imagery. |
| `.../MODIS_Terra_CorrectedReflectance_TrueColor/.../GoogleMapsCompatible_Level9/...jpg` | **verified** | Returns imagery. Kept as a documented alternative, not wired into the UI. |
| `.../MODIS_Terra_NDVI_8Day/default/{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png` | **verified** | See the trap below. |
| `.../epsg4326/best/MODIS_Terra_NDVI_8Day/default/{date}/250m/{z}/{row}/{col}.png` | **verified** | Used by the batch NDVI sampler. |
| `gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_NDVI.xml` | **verified** | 143 `ColorMapEntry` elements, each with a unique RGB, so the palette inverts exactly. |
| `api.open-meteo.com/v1/forecast` | docs-verified | The live API is blocked by `robots.txt` for the fetch tool available here, so the multi-coordinate response shape was taken from the documentation and the parser handles **both** the single-object and the list form. |
| `archive-api.open-meteo.com/v1/archive` | **not used** | See §4. |
| `api.open-meteo.com/v1/elevation` | docs-verified | Max 100 coordinates per request; returns `{"elevation": [...]}`. |
| `tiles.openfreemap.org/styles/positron` | **verified** | Valid MapLibre style; vector tiles from `tiles.openfreemap.org/planet`, glyphs from the same host. |
| `nominatim.openstreetmap.org` | docs-verified | Blocked by `robots.txt` here. Used client-side only, throttled to 1 req/s and cached. |
| USA-NPN | **dropped** | Deliberate — see §3. |
| Windy Webcams API | **not verified** | Needs an account. Kept strictly as an opt-in plugin behind `VITE_WINDY_KEY`; with no key, no request is made. |

### The GIBS trap worth writing down

`MODIS_Terra_NDVI_8Day` returns **HTTP 400** at
`GoogleMapsCompatible_Level6`, `Level7` and `Level8`, and only works at
`Level9`. The failure looks identical to "this layer does not exist", and it
cost real time here. The tile-matrix-set name is part of the layer's identity,
not a zoom hint — the correct name per layer is in
[`src/layers.ts`](src/layers.ts) and [`batch/config.py`](batch/config.py).

The colour map is at `MODIS_NDVI.xml`, **not** `MODIS_Terra_NDVI_8Day.xml`
(404). GIBS names colour maps after the palette, not the layer.

## 2. Region: Europe, defaulting to Poland

The brief's original bounding box was North America; it was changed to Europe
with Poland as the default view.

- **Data extent** is all of Europe (35–71.5 °N, 11 °W–32 °E) rather than Poland
  alone, so the app is useful to anyone in Europe without a rebuild. Poland is
  the map's opening view, not the limit of the data.
- **Resolution is 0.5°, not 0.25°.** At 0.25° Europe is about 11 000 land cells
  and roughly 220 Open-Meteo requests a night carrying 108 days × 2 variables ×
  50 locations each. That is a lot to ask of a free keyless service every night
  for a hobby map, and the model's real skill (±5 days at best) does not justify
  55 km resolution over 27 km. `--profile poland` gives 0.25° over Poland alone
  (~1000 cells) for anyone who wants it.
- The published `forecast.json` is **484 kB raw, 13 kB gzipped** — far inside
  the 600 kB budget, with room to go finer later.

### Model constants for Europe

The brief's constants were for North America and would have been wrong here.
Refitted by hand against three anchor points from published European autumn
phenology:

| Anchor | Latitude | Elevation | Target peak |
| --- | --- | --- | --- |
| Central Poland | 52 °N | 150 m | ~20 October |
| Northern Finland (*ruska*) | 68 °N | 200 m | ~12 September |
| Southern Italy | 40 °N | 200 m | ~15 November |

Solving gives `baseline_doy = 414.1 − 2.30·lat − 0.010·elev`. Check: the Alps
at 46.5 °N, 1500 m → 19 October, which matches larch turning in late October.

**Assumption:** longitude is ignored. Real European autumn is later on the
Atlantic fringe and earlier in the continental interior — Ireland runs later
than Belarus at the same latitude. A longitude or continentality term would
help and is the single most promising improvement to the baseline. It is left
out because there was no calibration data here to fit it against, and a
made-up coefficient is worse than an acknowledged omission.

**Assumption:** the model is clamped to days 228–340. Cells that hit a clamp
(mostly Iberia, southern Italy, Greece) are forced to `low` confidence, because
past the clamp the linear fit is extrapolating well outside its anchors. Much
of the Mediterranean canopy is evergreen anyway, so the honest answer there is
"this model does not really apply".

## 3. USA-NPN was dropped, not skipped

The brief listed USA-NPN for calibration. It is a **United States** phenology
network; it has no European observations and calibrating a European model
against it would be meaningless. The European equivalent is the
[PEP725](http://www.pep725.eu/) database, which requires registration and a
data-use agreement — that conflicts with "no accounts, reproducible build", so
it is not wired in either.

The constants above are therefore **hand-fitted to published anchor dates, not
statistically calibrated against an observation set.** That is the single
largest source of error in this app, and `CONTRIBUTING.md` names calibration as
the most valuable contribution someone could make.

## 4. Weather: forecast API only, no archive

`past_days=92` on the forecast endpoint reaches back to 1 September for any run
between 1 September and 1 December — the whole season. That makes the separate
archive API unnecessary: one endpoint, one code path, half the failure modes.
Outside that window `past_days` is clamped and the model falls back toward pure
climatology, which is correct behaviour for a run in, say, March.

## 5. Bundle budget: **not met as written**, and why

The brief asked for MapLibre GL JS **and** a total JS bundle under 150 kB
gzipped. These are mutually exclusive: MapLibre is a WebGL vector-tile renderer
and is 217 kB gzipped on its own. No configuration makes it smaller.

Measured (`npm run size`):

| | gzipped | budget |
| --- | --- | --- |
| App JS (entry + lazy chunks) | **7.3 kB** | 150 kB |
| App CSS | **2.2 kB** | 20 kB |
| MapLibre JS (deferred chunk) | **212.5 kB** | 260 kB |
| MapLibre CSS | **9.0 kB** | 16 kB |
| `forecast.json` | **12.6 kB** | 600 kB |
| **Cold first load** | **231 kB** | — |

The technology instruction was followed and the budget was missed, rather than
the reverse, because the alternative — a raster basemap behind a small map
library — means either OSM's tile servers (whose usage policy this app would
abuse) or a proprietary tile provider (explicitly excluded). Given the choice,
keyless open vector tiles were worth 80 kB.

What was done to soften it:

- MapLibre is a **dynamic import** in its own chunk. The shell, the forecast
  data and the detail panel are interactive before it arrives, and it stays in
  the browser cache across app deploys.
- Our own code — the part actually under our control — is 9.5 kB gzipped
  against a 150 kB budget.
- `npm run size` enforces both budgets separately in CI and prints the honest
  total, so this cannot quietly drift.

**If 150 kB total is a hard requirement for you**, replace `src/map.ts` with a
Leaflet-based renderer (~42 kB gzipped) drawing the choropleth on canvas over a
raster basemap you are licensed to use. Nothing else in the app changes: the
map module's interface is four methods.

## 6. Land mask: bundled bitmask, not a runtime lookup

Distinguishing land from sea needs data. The options were a geometry library
plus coastline polygons (heavy, and a build-time download), or the Open-Meteo
elevation trick of treating 0 m as water (wrong for the Netherlands, wrong for
the Po delta, and it burns requests on sea cells).

Instead, `global-land-mask` is used **once, at development time**, to bake a
0.25° bit-per-cell mask over Europe into
[`batch/data/landmask.json`](batch/data/landmask.json) — 4.7 kB, no runtime
dependency, regenerable with one documented script. The mask resolution is
independent of the forecast grid step, so changing the profile does not require
regenerating it.

Verified against known points: Warsaw and Kraków are land; the central Baltic
and the open Mediterranean are not.

## 7. Elevation is cached in the repo

Elevation does not change. The first live run fetches it and writes
`public/data/grid.json`; every later run reads that file and asks about nothing.
This turns a recurring cost into a one-off.

In `--offline` mode with no cache present, elevation is unknown, cells are
treated as sea level, and confidence drops to `low` — visible in the demo build
as an "elevation unavailable" chip. That is the intended degradation, not a bug.

## 8. NDVI needs Pillow, and is allowed to be absent

GIBS serves NDVI as a **colourised PNG**, so reading values back means decoding
the image and inverting the published palette. That needs an image decoder.

Rather than add Pillow to the core requirements (the brief asked for stdlib +
httpx + numpy) or hand-roll a PNG decoder, `batch/ndvi.py` imports Pillow
lazily and returns `{}` if it is missing, if the colour map is unreachable, or
if more than half the tiles fail. `requirements.txt` stays clean;
`requirements-dev.txt` and the nightly workflow install Pillow so the feature is
live in production.

NDVI can only ever advance a cell **one** state, and only a cell already
colouring. A cloud bank reads as a huge NDVI drop; without that guard, one
cloudy day would flip a green region to "past peak".

## 9. Two model bugs found by running it, worth recording

Both were caught by running the pipeline across three simulated dates and
comparing, not by the unit tests, which is a lesson in itself.

1. **The peak date walked backwards all season.** Accumulating cool nights up
   to *today* meant every cold night in November pulled the published peak
   earlier — Warsaw drifted 21 → 14 → 8 October across three run dates for the
   same season. Fixed by ending the accumulation window at the *climatological*
   peak: weather can only move a peak that has not happened yet. The estimate is
   now stable once the 16-day forecast covers the peak, and there is a
   regression test (`test_window_end_stops_accumulation_at_the_peak`).

2. **Southern cells hit the calendar clamp silently** and reported the same
   confidence as a well-constrained cell in Poland. Now `predict_cell` detects
   clamping and forces `low`.

## 10. One UI bug found by running it in a browser

With the basemap unreachable, the map fired no `load` event, the click handler
was never bound, and **clicking the map did nothing** — the exact failure the
"degrade gracefully" requirement exists to prevent. The handler is now bound in
the constructor, and layers are installed on `styledata` so they survive a style
swap. Separately, the offline fallback style carried `glyphs: undefined`, which
MapLibre rejects as invalid, leaving a blank map; the style is now minimal and
strictly valid.

Verified in headless Chromium with all outbound network blocked: the choropleth
renders, clicks resolve to cells, the panel fills in, and status chips report
"basemap unavailable".

## 11. Webcams ship as an empty, documented list

`public/data/webcams.json` contains **no entries**. Public webcam URLs could not
be verified from this environment, and shipping plausible-looking URLs that
404 — or worse, that point somewhere unintended — is worse than shipping none.
The file has a documented schema, the UI handles the empty case by hiding the
panel, `CONTRIBUTING.md` explains how to add entries, and the Windy plugin is
the ready-made path to live cams for anyone with a key.

## 12. Smaller choices

- **No cookie banner** because there are no cookies, no `localStorage`, and no
  analytics. Nothing to consent to.
- **Reverse geocoding is cosmetic** and arrives after the forecast renders. A
  slow or blocked Nominatim never delays the numbers; the panel shows
  coordinates instead.
- **`base: './'`** so the build works on a GitHub project page without
  configuration; `BASE_PATH=/` covers custom domains.
- **The nightly job refuses to publish** a file with fewer than 500 cells or one
  marked as demo data, so a partial upstream outage cannot overwrite good data
  with a stub.
- **Colour ramp** is defined once in `src/forecast.ts` and read by both the map
  and the legend, so they cannot drift apart. Lightness increases monotonically
  through the first four states, which is what carries the ordering for
  colour-blind viewers rather than hue alone.
- **`--offline` output is tagged `demo: true`** and the UI shows a "demo data"
  chip. Synthetic weather that looked like real weather would be the most
  dishonest thing this app could do.
