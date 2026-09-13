/**
 * Place search and reverse geocoding via Nominatim.
 *
 * Nominatim is keyless and free, and its usage policy asks for at most one
 * request a second and an identifying User-Agent/Referer. We throttle to one
 * request per second, debounce typing, and cache results, so a session costs a
 * handful of requests. Everything degrades to bare coordinates on failure.
 */

const ENDPOINT = 'https://nominatim.openstreetmap.org';
const MIN_INTERVAL_MS = 1000;

let lastCall = 0;
const cache = new Map<string, unknown>();

async function throttled<T>(url: string): Promise<T | null> {
  if (cache.has(url)) return cache.get(url) as T;

  const wait = Math.max(0, lastCall + MIN_INTERVAL_MS - Date.now());
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  lastCall = Date.now();

  try {
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    const json = (await res.json()) as T;
    cache.set(url, json);
    return json;
  } catch {
    return null;
  }
}

export interface SearchResult {
  label: string;
  lat: number;
  lon: number;
}

interface NominatimPlace {
  display_name?: string;
  name?: string;
  lat?: string;
  lon?: string;
  address?: Record<string, string>;
}

export async function searchPlaces(query: string, limit = 5): Promise<SearchResult[]> {
  const q = query.trim();
  if (q.length < 2) return [];
  const url =
    `${ENDPOINT}/search?format=jsonv2&limit=${limit}&addressdetails=0` +
    `&q=${encodeURIComponent(q)}`;
  const json = await throttled<NominatimPlace[]>(url);
  if (!Array.isArray(json)) return [];
  return json
    .filter((p) => p.lat && p.lon)
    .map((p) => ({
      label: p.display_name ?? p.name ?? q,
      lat: Number(p.lat),
      lon: Number(p.lon),
    }));
}

/** Best-effort place name for a point. Returns null rather than throwing. */
export async function reverseGeocode(lat: number, lon: number): Promise<string | null> {
  // Round to the neighbourhood: keeps the cache useful and the request count low.
  const url =
    `${ENDPOINT}/reverse?format=jsonv2&zoom=10&lat=${lat.toFixed(2)}&lon=${lon.toFixed(2)}`;
  const json = await throttled<NominatimPlace>(url);
  if (!json) return null;
  const a = json.address ?? {};
  const parts = [
    a.city ?? a.town ?? a.village ?? a.municipality ?? a.county ?? json.name,
    a.state ?? a.region,
    a.country,
  ].filter(Boolean);
  return parts.length ? parts.join(', ') : (json.display_name ?? null);
}

/** Trailing debounce, so typing does not spend the rate limit. */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let t: number | undefined;
  return (...args: A) => {
    if (t) window.clearTimeout(t);
    t = window.setTimeout(() => fn(...args), ms);
  };
}
