/**
 * Forecast data: loading, nearest-cell lookup, and the vocabulary the UI uses.
 *
 * The whole client-side data path lives here. One fetch of one JSON file, then
 * every click is an in-memory O(1) lookup -- no per-click network calls.
 */

export const STATES = [
  'green',
  'early',
  'near_peak',
  'peak',
  'past_peak',
  'bare',
] as const;

export type State = (typeof STATES)[number];
export type Confidence = 'low' | 'medium' | 'high';

export interface Cell {
  id: string;
  state: State;
  peak_start: string;
  peak: string;
  past_peak: string;
  confidence: Confidence;
  updated: string;
}

export interface Forecast {
  version: number;
  generated: string;
  today: string;
  profile: string;
  step: number;
  /** [west, south, east, north] */
  bbox: [number, number, number, number];
  /** [lon, lat, zoom] */
  center: [number, number, number];
  demo: boolean;
  sources: Record<string, string>;
  cells: Cell[];
}

/** Colour-blind-safe ramp, ordered along the progression. */
export const STATE_COLOR: Record<State, string> = {
  green: '#2f6b3a',
  early: '#8fb03e',
  near_peak: '#e8b13a',
  peak: '#d75f2b',
  past_peak: '#8a5a3b',
  bare: '#9aa3a8',
};

export const STATE_LABEL: Record<State, string> = {
  green: 'Still green',
  early: 'Early colour',
  near_peak: 'Near peak',
  peak: 'Peak',
  past_peak: 'Past peak',
  bare: 'Bare',
};

/**
 * An indexed forecast. Cells sit on a regular lat/lon grid, so a lookup is a
 * snap-to-grid plus a hash hit; the outward spiral only runs when the clicked
 * cell is missing (open water, or outside the modelled region).
 */
export class ForecastIndex {
  readonly data: Forecast;
  private readonly byId = new Map<string, Cell>();
  private readonly step: number;
  private readonly lat0: number;
  private readonly lon0: number;

  constructor(data: Forecast) {
    this.data = data;
    this.step = data.step;
    this.lat0 = data.bbox[1];
    this.lon0 = data.bbox[0];
    for (const c of data.cells) this.byId.set(c.id, c);
  }

  get cells(): Cell[] {
    return this.data.cells;
  }

  /** Centre of the grid cell containing (lat, lon). */
  snap(lat: number, lon: number): [number, number] {
    const r = Math.floor((lat - this.lat0) / this.step);
    const c = Math.floor((lon - this.lon0) / this.step);
    return [
      round2(this.lat0 + (r + 0.5) * this.step),
      round2(this.lon0 + (c + 0.5) * this.step),
    ];
  }

  /**
   * The cell covering (lat, lon), or the closest one within `maxRings` grid
   * steps. Returns null when nothing modelled is near -- mid-ocean, say.
   */
  nearest(lat: number, lon: number, maxRings = 3): Cell | null {
    const [slat, slon] = this.snap(lat, lon);
    const exact = this.byId.get(key(slat, slon));
    if (exact) return exact;

    let best: Cell | null = null;
    let bestDist = Infinity;
    for (let ring = 1; ring <= maxRings; ring++) {
      for (let dr = -ring; dr <= ring; dr++) {
        for (let dc = -ring; dc <= ring; dc++) {
          // Only the perimeter of each ring is new.
          if (Math.max(Math.abs(dr), Math.abs(dc)) !== ring) continue;
          const clat = round2(slat + dr * this.step);
          const clon = round2(slon + dc * this.step);
          const cell = this.byId.get(key(clat, clon));
          if (!cell) continue;
          const d = (clat - lat) ** 2 + ((clon - lon) * Math.cos((lat * Math.PI) / 180)) ** 2;
          if (d < bestDist) {
            bestDist = d;
            best = cell;
          }
        }
      }
      if (best) return best;
    }
    return null;
  }

  /** Whole-degree square polygons for the choropleth layer. */
  toGeoJSON(): GeoJSON.FeatureCollection {
    const h = this.step / 2;
    return {
      type: 'FeatureCollection',
      features: this.data.cells.map((cell) => {
        const [lat, lon] = cell.id.split(',').map(Number);
        return {
          type: 'Feature' as const,
          properties: { id: cell.id, state: cell.state },
          geometry: {
            type: 'Polygon' as const,
            coordinates: [[
              [lon - h, lat - h],
              [lon + h, lat - h],
              [lon + h, lat + h],
              [lon - h, lat + h],
              [lon - h, lat - h],
            ]],
          },
        };
      }),
    };
  }
}

function key(lat: number, lon: number): string {
  return `${lat.toFixed(2)},${lon.toFixed(2)}`;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Whole days between two ISO dates (b - a). */
export function daysBetween(a: string, b: string): number {
  const ms = Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z');
  return Math.round(ms / 86_400_000);
}

/** "today", "in 6 days", "12 days ago" -- for the timeline and the age chip. */
export function relativeDays(from: string, to: string): string {
  const d = daysBetween(from, to);
  if (d === 0) return 'today';
  if (d === 1) return 'tomorrow';
  if (d === -1) return 'yesterday';
  return d > 0 ? `in ${d} days` : `${-d} days ago`;
}

export function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00Z').toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
}

/**
 * How stale the data is, in days, from the run date to now. Used for the
 * "last updated" chip -- the app stays useful with old data, it just says so.
 */
export function ageInDays(forecast: Forecast, now = new Date()): number {
  const today = now.toISOString().slice(0, 10);
  return Math.max(0, daysBetween(forecast.today, today));
}

export async function loadForecast(url = 'data/forecast.json'): Promise<Forecast> {
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`forecast unavailable (HTTP ${res.status})`);
  const data = (await res.json()) as Forecast;
  if (!data || !Array.isArray(data.cells)) throw new Error('forecast is malformed');
  return data;
}
