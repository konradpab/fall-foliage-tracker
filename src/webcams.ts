/**
 * Nearby live views.
 *
 * Two independent sources, both optional:
 *   1. `public/data/webcams.json` -- a community-maintained list in the repo.
 *   2. The Windy Webcams API -- only if VITE_WINDY_KEY was set at build time.
 *
 * With neither, the panel hides itself. It never blocks the rest of the app.
 */

export type WebcamKind = 'page' | 'image' | 'mjpeg' | 'hls';

export interface Webcam {
  id: string;
  title: string;
  lat: number;
  lon: number;
  kind: WebcamKind;
  url: string;
  /** Where the stream came from, shown as attribution. */
  source?: string;
}

export interface WebcamFile {
  version: number;
  note?: string;
  cams: Webcam[];
}

const WINDY_KEY = import.meta.env.VITE_WINDY_KEY as string | undefined;
const WINDY_ENDPOINT = 'https://api.windy.com/webcams/api/v3/webcams';

export function haversineKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) *
      Math.cos((bLat * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export function nearest(cams: Webcam[], lat: number, lon: number, radiusKm = 60, limit = 4): Webcam[] {
  return cams
    .map((c) => ({ c, d: haversineKm(lat, lon, c.lat, c.lon) }))
    .filter((x) => x.d <= radiusKm)
    .sort((a, b) => a.d - b.d)
    .slice(0, limit)
    .map((x) => x.c);
}

export async function loadLocalWebcams(url = 'data/webcams.json'): Promise<Webcam[]> {
  try {
    const res = await fetch(url);
    if (!res.ok) return [];
    const file = (await res.json()) as WebcamFile;
    return Array.isArray(file.cams) ? file.cams : [];
  } catch {
    return [];
  }
}

/** Windy plugin. Returns [] when no key is configured, without a request. */
export async function loadWindyWebcams(lat: number, lon: number, radiusKm = 50): Promise<Webcam[]> {
  if (!WINDY_KEY) return [];
  const url =
    `${WINDY_ENDPOINT}?nearby=${lat.toFixed(3)},${lon.toFixed(3)},${Math.round(radiusKm)}` +
    `&limit=4&include=images,location`;
  try {
    const res = await fetch(url, { headers: { 'x-windy-api-key': WINDY_KEY } });
    if (!res.ok) return [];
    const json = (await res.json()) as {
      webcams?: {
        webcamId: number | string;
        title: string;
        location?: { latitude: number; longitude: number };
        images?: { current?: { preview?: string } };
      }[];
    };
    return (json.webcams ?? [])
      .filter((w) => w.location)
      .map((w) => ({
        id: `windy-${w.webcamId}`,
        title: w.title,
        lat: w.location!.latitude,
        lon: w.location!.longitude,
        kind: 'image' as const,
        url: w.images?.current?.preview ?? '',
        source: 'Windy Webcams',
      }))
      .filter((w) => w.url);
  } catch {
    return [];
  }
}

export function hasWindy(): boolean {
  return Boolean(WINDY_KEY);
}
