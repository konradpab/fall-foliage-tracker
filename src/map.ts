/**
 * The map: basemap, forecast choropleth, optional satellite overlay, date slider.
 *
 * Every remote thing here can fail, and each failure is contained: a dead
 * basemap falls back to a plain background, a dead tile source raises a chip in
 * the layer bar. The forecast choropleth is local data and always renders.
 */

import 'maplibre-gl/dist/maplibre-gl.css';
import maplibregl, { Map as MLMap } from 'maplibre-gl';
import {
  BASEMAP_STYLE,
  FALLBACK_STYLE,
  SAT_LAYERS,
  dateChoices,
  tileUrl,
  type SatLayer,
} from './layers';
import { ForecastIndex, STATES, STATE_COLOR } from './forecast';

const CHOROPLETH_SRC = 'forecast';
const SAT_SRC = 'satellite';

export type LayerId = 'forecast' | 'truecolor' | 'ndvi';

export interface MapHandlers {
  onPick: (lat: number, lon: number) => void;
  onSourceError: (which: string) => void;
}

export class FoliageMap {
  readonly map: MLMap;
  private index: ForecastIndex | null = null;
  private active: LayerId = 'forecast';
  private satDate: string | null = null;
  private ready = false;

  constructor(container: HTMLElement, center: [number, number, number], private h: MapHandlers) {
    this.map = new maplibregl.Map({
      container,
      style: BASEMAP_STYLE,
      center: [center[0], center[1]],
      zoom: center[2],
      minZoom: 3,
      maxZoom: 10,
      attributionControl: false,
      // Keeps the initial paint cheap on mobile.
      antialias: false,
    });

    this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    this.map.addControl(
      new maplibregl.GeolocateControl({ trackUserLocation: false }),
      'top-right',
    );

    this.map.on('error', (e: unknown) => {
      const msg = String((e as { error?: Error })?.error?.message ?? e);
      if (msg.includes('openfreemap')) this.h.onSourceError('basemap');
      else if (msg.includes('gibs')) this.h.onSourceError('satellite');
    });

    // If the style never arrives, draw something rather than nothing.
    const styleTimer = window.setTimeout(() => {
      if (!this.map.isStyleLoaded()) {
        this.h.onSourceError('basemap');
        try {
          this.map.setStyle(FALLBACK_STYLE as never);
        } catch {
          /* the map is unusable; the panel still works */
        }
      }
    }, 8000);

    // Picking must work even when the basemap never arrives, so the click
    // handler is bound now rather than inside the style-load callback.
    this.map.on('click', (ev) => this.h.onPick(ev.lngLat.lat, ev.lngLat.lng));

    const onStyle = () => {
      if (!this.map.isStyleLoaded()) return;
      window.clearTimeout(styleTimer);
      this.ready = true;
      this.map.getCanvas().style.cursor = 'crosshair';
      // A style swap wipes every source, so re-install on each new style too.
      this.installLayers();
    };
    this.map.on('load', onStyle);
    this.map.on('styledata', onStyle);
  }

  setForecast(index: ForecastIndex): void {
    this.index = index;
    if (this.ready) this.installLayers();
  }

  private installLayers(): void {
    if (!this.index || !this.ready) return;
    const geojson = this.index.toGeoJSON() as never;

    const existing = this.map.getSource(CHOROPLETH_SRC) as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(geojson);
    } else {
      this.map.addSource(CHOROPLETH_SRC, { type: 'geojson', data: geojson });
      // `match` keeps the colour ramp declarative, so the legend and the map
      // can never drift apart -- both read STATE_COLOR.
      const match: (string | string[])[] = ['match', ['get', 'state']];
      for (const s of STATES) match.push(s, STATE_COLOR[s]);
      match.push('#cccccc');

      this.map.addLayer({
        id: 'forecast-fill',
        type: 'fill',
        source: CHOROPLETH_SRC,
        paint: {
          'fill-color': match as never,
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.72, 9, 0.45],
        },
      });
      this.map.addLayer({
        id: 'forecast-selected',
        type: 'line',
        source: CHOROPLETH_SRC,
        filter: ['==', ['get', 'id'], ''],
        paint: { 'line-color': '#111', 'line-width': 2 },
      });
    }
    this.applyVisibility();
  }

  highlight(cellId: string | null): void {
    if (!this.map.getLayer('forecast-selected')) return;
    this.map.setFilter('forecast-selected', ['==', ['get', 'id'], cellId ?? '']);
  }

  setLayer(id: LayerId): void {
    this.active = id;
    if (id !== 'forecast') {
      const layer = SAT_LAYERS[id];
      const dates = dateChoices(layer);
      this.satDate = this.satDate ?? dates[dates.length - 1];
      this.setSatellite(layer, this.satDate);
    }
    this.applyVisibility();
  }

  setSatDate(date: string): void {
    this.satDate = date;
    if (this.active !== 'forecast') this.setSatellite(SAT_LAYERS[this.active], date);
  }

  private setSatellite(layer: SatLayer, date: string): void {
    if (!this.ready) return;
    // Tile URLs are immutable per (layer, date), so swap the whole source.
    if (this.map.getLayer('sat-raster')) this.map.removeLayer('sat-raster');
    if (this.map.getSource(SAT_SRC)) this.map.removeSource(SAT_SRC);
    this.map.addSource(SAT_SRC, {
      type: 'raster',
      tiles: [tileUrl(layer, date)],
      tileSize: 256,
      maxzoom: layer.maxzoom,
      attribution: layer.attribution,
    });
    const before = this.map.getLayer('forecast-fill') ? 'forecast-fill' : undefined;
    this.map.addLayer(
      { id: 'sat-raster', type: 'raster', source: SAT_SRC, paint: { 'raster-opacity': 0.9 } },
      before,
    );
    this.applyVisibility();
  }

  private applyVisibility(): void {
    const showForecast = this.active === 'forecast';
    for (const id of ['forecast-fill', 'forecast-selected']) {
      if (this.map.getLayer(id)) {
        this.map.setLayoutProperty(id, 'visibility', showForecast ? 'visible' : 'none');
      }
    }
    if (this.map.getLayer('sat-raster')) {
      this.map.setLayoutProperty('sat-raster', 'visibility', showForecast ? 'none' : 'visible');
    }
  }

  flyTo(lat: number, lon: number, zoom = 7): void {
    this.map.flyTo({ center: [lon, lat], zoom, duration: 800 });
  }
}
