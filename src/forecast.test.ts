import { describe, expect, it } from 'vitest';
import {
  ForecastIndex,
  ageInDays,
  daysBetween,
  relativeDays,
  type Cell,
  type Forecast,
} from './forecast';
import { dateChoices, tileUrl, SAT_LAYERS, daysAgo } from './layers';
import { haversineKm, nearest as nearestCam, type Webcam } from './webcams';

function cell(id: string, over: Partial<Cell> = {}): Cell {
  return {
    id,
    state: 'peak',
    peak_start: '2026-10-07',
    peak: '2026-10-14',
    past_peak: '2026-10-21',
    confidence: 'medium',
    updated: '2026-10-12',
    ...over,
  };
}

function forecast(cells: Cell[], step = 0.5): Forecast {
  return {
    version: 1,
    generated: '2026-10-12T06:00:00Z',
    today: '2026-10-12',
    profile: 'test',
    step,
    bbox: [-11, 35, 32, 71.5],
    center: [19.4, 52.0, 5.4],
    demo: false,
    sources: { weather: 'open-meteo' },
    cells,
  };
}

describe('nearest-cell lookup', () => {
  const idx = new ForecastIndex(
    forecast([cell('52.25,21.25'), cell('52.75,21.25'), cell('52.25,20.75')]),
  );

  it('snaps a coordinate to its grid-cell centre', () => {
    expect(idx.snap(52.2, 21.0)).toEqual([52.25, 21.25]);
    expect(idx.snap(52.49, 21.49)).toEqual([52.25, 21.25]);
    expect(idx.snap(52.51, 21.51)).toEqual([52.75, 21.75]);
  });

  it('finds the cell containing a point', () => {
    expect(idx.nearest(52.23, 21.01)?.id).toBe('52.25,21.25');
    expect(idx.nearest(52.9, 21.3)?.id).toBe('52.75,21.25');
  });

  it('is exact on the cell centre itself', () => {
    expect(idx.nearest(52.25, 21.25)?.id).toBe('52.25,21.25');
  });

  it('falls back to the closest neighbour when the cell is missing', () => {
    // 52.25,20.25 is not in the set; 52.25,20.75 is one step west.
    expect(idx.nearest(52.25, 20.3)?.id).toBe('52.25,20.75');
  });

  it('returns null when nothing is within reach', () => {
    expect(idx.nearest(40.0, 0.0)).toBeNull();
  });

  it('respects the search radius', () => {
    expect(idx.nearest(54.5, 21.25, 1)).toBeNull();
    expect(idx.nearest(54.5, 21.25, 5)?.id).toBe('52.75,21.25');
  });

  it('handles a finer grid step', () => {
    const fine = new ForecastIndex(forecast([cell('52.125,21.125')], 0.25));
    expect(fine.snap(52.2, 21.2)).toEqual([52.13, 21.13]);
  });
});

describe('geojson output', () => {
  it('emits one square per cell, sized to the grid step', () => {
    const idx = new ForecastIndex(forecast([cell('52.25,21.25')], 0.5));
    const fc = idx.toGeoJSON();
    expect(fc.features).toHaveLength(1);
    const ring = (fc.features[0].geometry as GeoJSON.Polygon).coordinates[0];
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual([21.0, 52.0]);
    expect(ring[2]).toEqual([21.5, 52.5]);
    expect(ring[0]).toEqual(ring[4]);
  });

  it('carries the state through for data-driven styling', () => {
    const idx = new ForecastIndex(forecast([cell('52.25,21.25', { state: 'bare' })]));
    expect(idx.toGeoJSON().features[0].properties).toMatchObject({ state: 'bare' });
  });
});

describe('dates', () => {
  it('counts whole days between ISO dates', () => {
    expect(daysBetween('2026-10-01', '2026-10-14')).toBe(13);
    expect(daysBetween('2026-10-14', '2026-10-01')).toBe(-13);
  });

  it('spans a month boundary correctly', () => {
    expect(daysBetween('2026-10-28', '2026-11-04')).toBe(7);
  });

  it('phrases relative days for the timeline', () => {
    expect(relativeDays('2026-10-12', '2026-10-12')).toBe('today');
    expect(relativeDays('2026-10-12', '2026-10-13')).toBe('tomorrow');
    expect(relativeDays('2026-10-12', '2026-10-18')).toBe('in 6 days');
    expect(relativeDays('2026-10-12', '2026-10-02')).toBe('10 days ago');
  });

  it('reports data age and never goes negative', () => {
    const f = forecast([]);
    expect(ageInDays(f, new Date('2026-10-15T09:00:00Z'))).toBe(3);
    expect(ageInDays(f, new Date('2026-10-12T09:00:00Z'))).toBe(0);
    expect(ageInDays(f, new Date('2026-10-10T09:00:00Z'))).toBe(0);
  });
});

describe('GIBS layers', () => {
  it('builds a WMTS url with row before column', () => {
    const url = tileUrl(SAT_LAYERS.ndvi, '2026-10-09');
    expect(url).toContain('MODIS_Terra_NDVI_8Day/default/2026-10-09/GoogleMapsCompatible_Level9');
    expect(url.endsWith('/{z}/{y}/{x}.png')).toBe(true);
  });

  it('offers 30 dates ending at the layer lag', () => {
    const now = new Date('2026-10-12T00:00:00Z');
    const dates = dateChoices(SAT_LAYERS.ndvi, 30, now);
    expect(dates).toHaveLength(30);
    expect(dates[29]).toBe('2026-10-09'); // 3-day lag
    expect(dates[0] < dates[29]).toBe(true);
  });

  it('walks back across a month boundary', () => {
    expect(daysAgo(15, new Date('2026-10-10T00:00:00Z'))).toBe('2026-09-25');
  });
});

describe('webcam proximity', () => {
  const cams: Webcam[] = [
    { id: 'a', title: 'Zakopane', lat: 49.3, lon: 19.95, kind: 'page', url: 'https://example.org/a' },
    { id: 'b', title: 'Warsaw', lat: 52.23, lon: 21.01, kind: 'page', url: 'https://example.org/b' },
  ];

  it('measures distance sanely', () => {
    // Warsaw to Krakow is about 250 km.
    expect(haversineKm(52.23, 21.01, 50.06, 19.94)).toBeGreaterThan(230);
    expect(haversineKm(52.23, 21.01, 50.06, 19.94)).toBeLessThan(270);
    expect(haversineKm(52.23, 21.01, 52.23, 21.01)).toBe(0);
  });

  it('returns only cams inside the radius, closest first', () => {
    expect(nearestCam(cams, 52.2, 21.0, 60).map((c) => c.id)).toEqual(['b']);
    expect(nearestCam(cams, 49.3, 19.9, 60).map((c) => c.id)).toEqual(['a']);
    expect(nearestCam(cams, 45.0, 9.0, 60)).toEqual([]);
  });
});
