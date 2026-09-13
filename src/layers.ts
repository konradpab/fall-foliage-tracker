/**
 * NASA GIBS satellite overlays.
 *
 * All three layers are keyless WMTS in EPSG:3857, so MapLibre can consume them
 * as ordinary raster sources. The tile-matrix-set names below were verified
 * against the live service; getting them wrong is what produces a silent 400.
 */

export interface SatLayer {
  id: string;
  label: string;
  /** GIBS layer identifier. */
  layer: string;
  tms: string;
  ext: 'png' | 'jpg';
  maxzoom: number;
  attribution: string;
  /** Days behind today the newest usable composite normally sits. */
  lagDays: number;
}

const GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best';
const NASA_ATTR =
  '<a href="https://earthdata.nasa.gov/gibs" target="_blank" rel="noopener">NASA EOSDIS GIBS</a>';

export const SAT_LAYERS: Record<string, SatLayer> = {
  truecolor: {
    id: 'truecolor',
    label: 'Satellite',
    layer: 'VIIRS_SNPP_CorrectedReflectance_TrueColor',
    tms: 'GoogleMapsCompatible_Level9',
    ext: 'jpg',
    maxzoom: 9,
    attribution: NASA_ATTR,
    lagDays: 1,
  },
  ndvi: {
    id: 'ndvi',
    label: 'Vegetation (NDVI)',
    layer: 'MODIS_Terra_NDVI_8Day',
    tms: 'GoogleMapsCompatible_Level9',
    ext: 'png',
    maxzoom: 9,
    attribution: NASA_ATTR,
    lagDays: 3,
  },
};

export function tileUrl(layer: SatLayer, date: string): string {
  return `${GIBS}/${layer.layer}/default/${date}/${layer.tms}/{z}/{y}/{x}.${layer.ext}`;
}

/** ISO date `n` days before today, in UTC. */
export function daysAgo(n: number, now = new Date()): string {
  const d = new Date(now.getTime() - n * 86_400_000);
  return d.toISOString().slice(0, 10);
}

/** The 30 most recent dates a satellite layer can show, newest last. */
export function dateChoices(layer: SatLayer, count = 30, now = new Date()): string[] {
  const out: string[] = [];
  for (let i = count - 1 + layer.lagDays; i >= layer.lagDays; i--) {
    out.push(daysAgo(i, now));
  }
  return out;
}

/** Keyless vector basemap. No Mapbox, no Google, no API key. */
export const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron';

/**
 * Drawn if the basemap style itself cannot be reached. Deliberately minimal and
 * strictly valid: an invalid style is rejected outright and would leave a blank
 * map with no forecast on it, which is the one outcome worse than no basemap.
 */
export const FALLBACK_STYLE = {
  version: 8 as const,
  name: 'offline-fallback',
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background' as const,
      paint: { 'background-color': '#e6e2dc' },
    },
  ],
};
