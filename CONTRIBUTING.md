# Contributing

This project is meant to stay boring and durable: no server, no accounts, no
paid services, nothing that needs babysitting. Contributions that keep it that
way are very welcome.

## Getting set up

```bash
pip install -r requirements-dev.txt
npm install

python -m batch.run --offline   # demo data, no network needed
npm run dev
```

Before opening a pull request:

```bash
python -m pytest
npm test
npm run build && npm run size
```

## The most valuable contribution: calibration

The phenology constants in `batch/config.py` are **hand-fitted to three
published anchor dates**, not calibrated against observations. See
[DECISIONS.md §2 and §3](DECISIONS.md). If you have access to observed European
autumn phenology — PEP725, a national network, or even a few years of careful
local notes — refitting `BASELINE_A`, `BASELINE_B_LAT` and `BASELINE_C_ELEV`
against real data would improve this app more than any feature.

The second most valuable: **a longitude or continentality term**. European
autumn runs later on the Atlantic fringe than in the continental interior at
the same latitude, and the model currently ignores this entirely.

If you change a model constant, say in the pull request what you fitted it
against, and update the table in `README.md`.

## Adding a webcam

Edit `public/data/webcams.json`. Entries must be:

- **publicly accessible** — no login, no API key, no paywall;
- **published deliberately** by the operator as a public webcam (a park
  authority, a road agency, a ski resort, a municipality). Do not add a camera
  someone left exposed by accident;
- **in or near the modelled region**, and pointed at something with trees in it;
- **stable** — prefer an official page over a hotlinked stream that will rotate.

```json
{
  "id": "unique-kebab-case-id",
  "title": "Human-readable place name",
  "lat": 49.30,
  "lon": 19.94,
  "kind": "page",
  "url": "https://example.org/webcam",
  "source": "Who publishes it"
}
```

`kind` is one of:

| kind | meaning |
| --- | --- |
| `page` | a link to a page hosting the camera — always safe |
| `image` | a still image URL that refreshes; rendered as a thumbnail |
| `mjpeg` | an MJPEG stream; rendered as a thumbnail |
| `hls` | an HLS stream URL; currently rendered as a link |

Prefer `page` unless you are confident the direct URL is intended for embedding
and permits hotlinking. Broken thumbnails hide themselves at runtime, but a
dead entry is still noise — please check the link before submitting.

## Changing the region or grid

`batch/config.py` holds every tunable. Add a `Profile` rather than editing an
existing one, so other deployments keep working. Watch the cost: halving the
step quadruples both the cell count and the number of Open-Meteo requests. Keep
`forecast.json` under 600 kB gzipped and the nightly job under a few hundred
requests — this runs on free, keyless services and should not be greedy with
them.

If your region falls outside 34–72 °N, 12 °W–34 °E, regenerate the land mask:

```bash
pip install global-land-mask
# edit the bbox at the top of batch/scripts/gen_landmask.py
python batch/scripts/gen_landmask.py
```

## Code conventions

**Python.** Standard library plus `httpx` and `numpy` in `requirements.txt`;
anything else must be an optional import that degrades to a no-op, the way
`batch/ndvi.py` handles Pillow. Model logic goes in `batch/model.py` as pure
functions with no I/O — that is what makes it testable, and every rule there
has a unit test with fixed inputs and fixed outputs.

**TypeScript.** No framework, no state library. `strict` is on and the build
runs `tsc --noEmit`. Keep our own JavaScript small; `npm run size` fails the
build if the app chunk grows past its budget.

**Failure handling is a feature.** Every remote source must degrade to a chip
in the status bar and a working app. If you add a data source, add its failure
path in the same pull request, and make sure the app still does something
sensible with the network switched off entirely.

**No new runtime dependencies** without a good reason, and no dependency that
needs an account, a key or a paid tier on the core path. Optional plugins behind
an environment variable are fine — see the Windy integration.

## Reporting a wrong forecast

Please include the grid cell id from the panel (for example `52.25,21.25`), the
date, what the app said, and what you actually saw. Local observations are how
the model gets better; there is an issue template for exactly this.

## Licence

By contributing you agree that your contributions are licensed under the
[MIT Licence](LICENSE).
