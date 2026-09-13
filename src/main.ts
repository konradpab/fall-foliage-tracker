/**
 * App wiring. Loads the forecast once, then every interaction is local.
 */

import './style.css';

import type { FoliageMap, LayerId } from './map';
import { SAT_LAYERS, dateChoices } from './layers';
import {
  ForecastIndex,
  STATES,
  STATE_COLOR,
  STATE_LABEL,
  ageInDays,
  formatDate,
  loadForecast,
} from './forecast';
import { renderPanel } from './panel';
import { debounce, reverseGeocode, searchPlaces } from './search';
import { hasWindy, loadLocalWebcams, loadWindyWebcams, nearest, type Webcam } from './webcams';

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

const els = {
  map: $('#map'),
  panel: $('#panel-body'),
  sheet: $<HTMLElement>('#sheet'),
  chips: $('#layer-chips'),
  slider: $<HTMLInputElement>('#date-slider'),
  sliderWrap: $('#date-slider-wrap'),
  sliderLabel: $('#date-label'),
  legend: $('#legend'),
  search: $<HTMLInputElement>('#search'),
  results: $('#search-results'),
  status: $('#status-chips'),
  webcams: $('#webcams'),
};

let index: ForecastIndex | null = null;
let map: FoliageMap | null = null;
let localCams: Webcam[] = [];
let selected: { lat: number; lon: number } | null = null;
let requestSeq = 0;

boot();

async function boot(): Promise<void> {
  renderLegend();

  let forecast;
  try {
    forecast = await loadForecast();
  } catch (err) {
    chip('forecast unavailable', 'error');
    els.panel.innerHTML = `
      <div class="empty">
        <h2>Forecast unavailable</h2>
        <p>The nightly data file could not be loaded, so there is nothing to
           show yet. The map still works.</p>
        <p class="muted">${(err as Error).message}</p>
      </div>`;
    void startMap([19.4, 52.0, 5.0]);
    return;
  }

  index = new ForecastIndex(forecast);
  void startMap(forecast.center);
  renderStatus();

  loadLocalWebcams().then((cams) => {
    localCams = cams;
  });

  wireLayerChips();
  wireSearch();
  renderPanel(els.panel, forecast, null, null, null);
}

/**
 * MapLibre is by far the largest thing we ship, so it is loaded on its own,
 * after the shell has painted. Search and the panel work without it.
 */
async function startMap(center: [number, number, number]): Promise<void> {
  const { FoliageMap } = await import('./map');
  map = new FoliageMap(els.map, center, {
    onPick: pick,
    onSourceError: (which) => chip(`${which} unavailable`, 'warn'),
  });
  if (index) map.setForecast(index);
}

// --- interaction ----------------------------------------------------------

function pick(lat: number, lon: number): void {
  if (!index) return;
  const seq = ++requestSeq;
  selected = { lat, lon };
  const cell = index.nearest(lat, lon);
  map?.highlight(cell?.id ?? null);
  renderPanel(els.panel, index.data, cell, selected, { label: '', pending: true });
  els.sheet.classList.add('open');

  // The name is cosmetic, so it arrives late and never blocks the numbers.
  reverseGeocode(lat, lon).then((name) => {
    if (seq !== requestSeq || !index) return;
    renderPanel(els.panel, index.data, cell, selected, name ? { label: name, pending: false } : null);
    renderWebcams(lat, lon);
  });
  renderWebcams(lat, lon);
}

async function renderWebcams(lat: number, lon: number): Promise<void> {
  const seq = requestSeq;
  const cams = [...nearest(localCams, lat, lon), ...(await loadWindyWebcams(lat, lon))];
  if (seq !== requestSeq) return;

  if (!cams.length) {
    els.webcams.innerHTML = hasWindy()
      ? '<h3>Nearby live views</h3><p class="muted">No public webcams within 60 km.</p>'
      : '';
    return;
  }
  els.webcams.innerHTML = `
    <h3>Nearby live views</h3>
    <ul class="cams">
      ${cams
        .map((c) =>
          c.kind === 'image' || c.kind === 'mjpeg'
            ? `<li><a href="${attr(c.url)}" target="_blank" rel="noopener">
                 <img src="${attr(c.url)}" alt="${attr(c.title)}" loading="lazy"
                      onerror="this.closest('li').classList.add('dead')">
                 <span>${text(c.title)}</span></a></li>`
            : `<li><a href="${attr(c.url)}" target="_blank" rel="noopener">${text(c.title)} &nearr;</a></li>`,
        )
        .join('')}
    </ul>`;
}

function wireLayerChips(): void {
  const ids: LayerId[] = ['forecast', 'truecolor', 'ndvi'];
  const labels: Record<LayerId, string> = {
    forecast: 'Forecast',
    truecolor: SAT_LAYERS.truecolor.label,
    ndvi: SAT_LAYERS.ndvi.label,
  };
  els.chips.innerHTML = ids
    .map(
      (id, i) =>
        `<button class="chip${i === 0 ? ' on' : ''}" data-layer="${id}"
                 aria-pressed="${i === 0}">${labels[id]}</button>`,
    )
    .join('');

  els.chips.addEventListener('click', (ev) => {
    const btn = (ev.target as HTMLElement).closest<HTMLButtonElement>('[data-layer]');
    if (!btn) return;
    const id = btn.dataset.layer as LayerId;
    for (const b of els.chips.querySelectorAll('button')) {
      b.classList.toggle('on', b === btn);
      b.setAttribute('aria-pressed', String(b === btn));
    }
    map?.setLayer(id);
    toggleSlider(id);
  });

  els.slider.addEventListener('input', () => {
    const id = currentLayer();
    if (id === 'forecast') return;
    const dates = dateChoices(SAT_LAYERS[id]);
    const date = dates[Number(els.slider.value)];
    els.sliderLabel.textContent = formatDate(date);
    map?.setSatDate(date);
  });
}

function currentLayer(): LayerId {
  return (els.chips.querySelector('.on') as HTMLElement)?.dataset.layer as LayerId;
}

function toggleSlider(id: LayerId): void {
  const show = id !== 'forecast';
  els.sliderWrap.hidden = !show;
  if (!show) return;
  const dates = dateChoices(SAT_LAYERS[id]);
  els.slider.max = String(dates.length - 1);
  els.slider.value = String(dates.length - 1);
  els.sliderLabel.textContent = formatDate(dates[dates.length - 1]);
  map?.setSatDate(dates[dates.length - 1]);
}

function wireSearch(): void {
  const run = debounce(async (q: string) => {
    if (q.trim().length < 2) {
      els.results.innerHTML = '';
      els.results.hidden = true;
      return;
    }
    const hits = await searchPlaces(q);
    els.results.hidden = hits.length === 0;
    els.results.innerHTML = hits
      .map(
        (h) =>
          `<li><button data-lat="${h.lat}" data-lon="${h.lon}">${text(h.label)}</button></li>`,
      )
      .join('');
  }, 450);

  els.search.addEventListener('input', () => run(els.search.value));
  els.results.addEventListener('click', (ev) => {
    const btn = (ev.target as HTMLElement).closest<HTMLButtonElement>('button[data-lat]');
    if (!btn) return;
    const lat = Number(btn.dataset.lat);
    const lon = Number(btn.dataset.lon);
    els.results.hidden = true;
    els.search.value = '';
    map?.flyTo(lat, lon);
    pick(lat, lon);
  });
  document.addEventListener('click', (ev) => {
    if (!(ev.target as HTMLElement).closest('.search')) els.results.hidden = true;
  });
}

// --- chrome ---------------------------------------------------------------

function renderLegend(): void {
  els.legend.innerHTML = STATES.map(
    (s) =>
      `<li><span class="sw" style="background:${STATE_COLOR[s]}"></span>${STATE_LABEL[s]}</li>`,
  ).join('');
}

function renderStatus(): void {
  if (!index) return;
  const { demo, sources } = index.data;
  const age = ageInDays(index.data);
  if (demo) chip('demo data', 'warn');
  chip(age === 0 ? 'updated today' : `updated ${age} day${age === 1 ? '' : 's'} ago`,
       age > 3 ? 'warn' : 'ok');
  for (const [name, value] of Object.entries(sources)) {
    if (value === 'unavailable') chip(`${name} unavailable`, 'warn');
  }
}

function chip(label: string, kind: 'ok' | 'warn' | 'error'): void {
  const el = document.createElement('span');
  el.className = `status ${kind}`;
  el.textContent = label;
  els.status.appendChild(el);
}

function text(s: string): string {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function attr(s: string): string {
  return text(s).replace(/"/g, '&quot;');
}
