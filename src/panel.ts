/**
 * The detail panel: state badge, peak-window timeline, confidence, provenance,
 * and a plain-language explanation of where the number came from.
 */

import {
  STATE_COLOR,
  STATE_LABEL,
  daysBetween,
  formatDate,
  relativeDays,
  type Cell,
  type Forecast,
} from './forecast';

export interface PlaceName {
  label: string;
  pending: boolean;
}

export function renderPanel(
  el: HTMLElement,
  forecast: Forecast,
  cell: Cell | null,
  coords: { lat: number; lon: number } | null,
  place: PlaceName | null,
): void {
  if (!coords) {
    el.innerHTML = `
      <div class="empty">
        <h2>Pick a place</h2>
        <p>Tap anywhere on the map, or search, to see where the leaves are and
           when they are expected to peak.</p>
      </div>`;
    return;
  }

  const coordLine = `${coords.lat.toFixed(2)}, ${coords.lon.toFixed(2)}`;
  const named = Boolean(place?.label);
  const where = place?.label || coordLine;
  // Without a place name the heading is already the coordinates; don't repeat them.
  const coordsHtml = named ? `<p class="coords">${coordLine}</p>` : '';

  if (!cell) {
    el.innerHTML = `
      <h2>${escapeHtml(where)}</h2>
      ${coordsHtml}
      <div class="notice">No forecast here. The model covers land inside the
        mapped region only &mdash; this looks like open water or a spot outside it.</div>`;
    return;
  }

  el.innerHTML = `
    <h2>${escapeHtml(where)}${place?.pending ? '<span class="spin" aria-hidden="true"></span>' : ''}</h2>
    ${coordsHtml}
    ${badge(cell)}
    ${timeline(forecast.today, cell)}
    ${facts(forecast, cell)}
    ${explainer()}`;
}

function badge(cell: Cell): string {
  return `<p class="badge" style="--badge:${STATE_COLOR[cell.state]}">
      <span class="dot" aria-hidden="true"></span>${STATE_LABEL[cell.state]}
    </p>`;
}

/**
 * A horizontal bar spanning peak_start .. past_peak, padded either side, with a
 * marker for today. Pure layout arithmetic -- no chart library.
 */
function timeline(today: string, cell: Cell): string {
  const pad = 10;
  const span = Math.max(daysBetween(cell.peak_start, cell.past_peak), 1);
  const start = -pad;
  const end = span + pad;
  const pos = (iso: string) =>
    ((daysBetween(cell.peak_start, iso) - start) / (end - start)) * 100;

  const todayPos = Math.min(Math.max(pos(today), 0), 100);
  const left = pos(cell.peak_start);
  const width = pos(cell.past_peak) - left;
  const inRange = daysBetween(cell.peak_start, today) >= start &&
    daysBetween(cell.peak_start, today) <= end;

  return `
    <div class="timeline" role="img"
         aria-label="Peak window ${formatDate(cell.peak_start)} to ${formatDate(cell.past_peak)}; today is ${relativeDays(today, cell.peak)} from peak">
      <div class="track">
        <div class="window" style="left:${left}%;width:${width}%"></div>
        <div class="peak" style="left:${pos(cell.peak)}%"></div>
        ${inRange ? `<div class="today" style="left:${todayPos}%"><span>today</span></div>` : ''}
      </div>
      <div class="ticks">
        <span>${formatDate(cell.peak_start)}</span>
        <span class="mid">peak ${formatDate(cell.peak)}</span>
        <span>${formatDate(cell.past_peak)}</span>
      </div>
    </div>`;
}

function facts(forecast: Forecast, cell: Cell): string {
  const rel = relativeDays(forecast.today, cell.peak);
  return `
    <dl class="facts">
      <div><dt>Peak</dt><dd>${formatDate(cell.peak)} <span class="muted">(${rel})</span></dd></div>
      <div><dt>Window</dt><dd>${formatDate(cell.peak_start)} &ndash; ${formatDate(cell.past_peak)}</dd></div>
      <div><dt>Confidence</dt><dd class="conf conf-${cell.confidence}">${cell.confidence}</dd></div>
      <div><dt>Grid cell</dt><dd class="muted">${cell.id} (${forecast.step}&deg;)</dd></div>
    </dl>`;
}

function explainer(): string {
  return `
    <details class="explain">
      <summary>How is this predicted?</summary>
      <p>Each grid cell gets a baseline peak date from its latitude and
         elevation &mdash; later toward the south, earlier high up. Daily
         temperatures since 1 September then shift that date: cold nights pull
         it earlier, hot days push it later, and a hard freeze ends the season
         outright.</p>
      <p>Satellite vegetation greenness (NDVI) is compared against a mid-August
         baseline and can nudge a cell one step further along when the leaves
         have visibly turned. It is a rule-based model, not a measurement:
         treat it as a good guess, not a promise.</p>
    </details>`;
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!,
  );
}
