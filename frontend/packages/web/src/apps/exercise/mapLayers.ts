import type { AnyLayer as Layer, AnySourceData as Source, GeoJSONSource, Map as MapboxMap } from 'mapbox-gl';
import type { FrameData, StaticData } from './scene';
import type { LightPreset } from './types';

const empty = { type: 'FeatureCollection', features: [] } as const;

/** Layers a click can pick a ship from, topmost first. */
export const PICK_LAYERS = ['ship-markers', 'ship-parts', 'ship-hulls', 'ship-halos'];

/** Source id to the data it carries. Every source starts empty and is filled by `setFrameData` and `setStaticData`. */
const SOURCES: Record<string, Source> = {
  'ex-halos': { type: 'geojson', data: empty },
  'ex-foam': { type: 'geojson', data: empty },
  'ex-lights': { type: 'geojson', data: empty },
  'ex-glows': { type: 'geojson', data: empty },
  'ex-routes': { type: 'geojson', data: empty },
  'ex-waypoints': { type: 'geojson', data: empty },
  'ex-trails': { type: 'geojson', data: empty, lineMetrics: true },
  'ex-hulls': { type: 'geojson', data: empty },
  'ex-parts': { type: 'geojson', data: empty },
  'ex-overlays': { type: 'geojson', data: empty },
  'ex-markers': { type: 'geojson', data: empty },
};

/** How much of the lighting shows at each time of day. Lights are barely there at noon and blaze at night. */
export const LIGHT_LEVEL: Record<LightPreset, { pillars: number; glow: number }> = {
  day: { pillars: 0.4, glow: 0 },
  dawn: { pillars: 0.85, glow: 0.35 },
  dusk: { pillars: 1, glow: 0.8 },
  night: { pillars: 1, glow: 1 },
};

/** Bloom radius in screen pixels at zoom 0 per meter of light size, at about 33 degrees north (a few percent off elsewhere). */
const GLOW_PX0 = (512 * 4) / (40_075_016.686 * Math.cos((33 * Math.PI) / 180));

const FONT = ['DIN Pro Bold', 'Arial Unicode MS Bold'];
const get = (key: string) => ['get', key];

/** Overlay layers are drawn in the Standard style's 'middle' slot so they sit with its 3D lighting; other styles ignore it. */
const slot = { slot: 'middle' } as const;

function layers(): Layer[] {
  return [
    {
      id: 'ship-halos',
      type: 'fill',
      source: 'ex-halos',
      ...slot,
      paint: {
        'fill-color': get('color'),
        'fill-opacity': ['case', get('selected'), 0.5, 0.28],
        'fill-emissive-strength': 1,
      },
    },
    {
      id: 'ship-foam',
      type: 'fill',
      source: 'ex-foam',
      ...slot,
      paint: { 'fill-color': '#f4fbff', 'fill-opacity': ['*', get('foam'), 0.55], 'fill-emissive-strength': 0.9 },
    },
    {
      id: 'route-lines',
      type: 'line',
      source: 'ex-routes',
      ...slot,
      layout: { 'line-cap': 'round' },
      paint: {
        'line-color': get('color'),
        'line-width': ['case', get('selected'), 2.5, 1.5],
        'line-opacity': ['case', get('selected'), 0.9, 0.45],
        'line-dasharray': [2, 2],
        'line-emissive-strength': 1,
      },
    },
    {
      id: 'wake-trails',
      type: 'line',
      source: 'ex-trails',
      ...slot,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-width': ['interpolate', ['exponential', 2], ['zoom'], 0, get('widthPx0'), 24, ['*', get('widthPx0'), 16777216]],
        'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, 'rgba(255,255,255,0.85)', 0.25, 'rgba(235,245,255,0.45)', 1, 'rgba(235,245,255,0)'],
        'line-blur': 2,
        'line-opacity': 0.85,
        'line-emissive-strength': 0.4,
      },
    },
    {
      id: 'ship-hulls',
      type: 'fill-extrusion',
      source: 'ex-hulls',
      ...slot,
      paint: {
        'fill-extrusion-color': get('color'),
        'fill-extrusion-height': get('height'),
        'fill-extrusion-base': get('base'),
        'fill-extrusion-opacity': 1,
        'fill-extrusion-vertical-gradient': true,
        'fill-extrusion-ambient-occlusion-intensity': 0.35,
        'fill-extrusion-emissive-strength': 0.25,
      },
    },
    {
      id: 'ship-parts',
      type: 'fill-extrusion',
      source: 'ex-parts',
      ...slot,
      paint: {
        'fill-extrusion-color': get('color'),
        'fill-extrusion-height': get('height'),
        'fill-extrusion-base': get('base'),
        'fill-extrusion-opacity': 1,
        'fill-extrusion-vertical-gradient': true,
        'fill-extrusion-ambient-occlusion-intensity': 0.35,
        'fill-extrusion-emissive-strength': 0.25,
      },
    },
    {
      id: 'ship-lights',
      type: 'fill-extrusion',
      source: 'ex-lights',
      ...slot,
      paint: {
        'fill-extrusion-color': get('color'),
        'fill-extrusion-height': get('height'),
        'fill-extrusion-base': get('base'),
        'fill-extrusion-opacity': LIGHT_LEVEL.day.pillars,
        'fill-extrusion-emissive-strength': 1,
        'fill-extrusion-cast-shadows': false,
      },
    },
    {
      id: 'overlay-selection',
      type: 'line',
      source: 'ex-overlays',
      ...slot,
      filter: ['==', get('kind'), 'selection'],
      paint: { 'line-color': get('color'), 'line-width': 2, 'line-opacity': 0.9, 'line-emissive-strength': 1 },
    },
    {
      id: 'overlay-range',
      type: 'line',
      source: 'ex-overlays',
      ...slot,
      filter: ['==', get('kind'), 'range'],
      paint: { 'line-color': get('color'), 'line-width': 1.5, 'line-opacity': 0.9, 'line-dasharray': [4, 3], 'line-emissive-strength': 1 },
    },
    {
      id: 'light-glows',
      type: 'circle',
      source: 'ex-glows',
      ...slot,
      paint: {
        'circle-color': get('color'),
        'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 0, ['*', get('sizeM'), GLOW_PX0], 24, ['*', get('sizeM'), GLOW_PX0 * 16777216]],
        'circle-blur': 1,
        'circle-opacity': LIGHT_LEVEL.day.glow,
        'circle-emissive-strength': 1,
      },
    },
    {
      id: 'ship-markers',
      type: 'circle',
      source: 'ex-markers',
      ...slot,
      paint: {
        'circle-color': get('color'),
        'circle-radius': ['case', get('selected'), 8, 6],
        'circle-stroke-color': '#0a1628',
        'circle-stroke-width': 2,
        // Ships are drawn to scale up close; the dot takes over once they are too small to see.
        'circle-opacity': ['interpolate', ['linear'], ['zoom'], 11.5, 1, 14, 0],
        'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 11.5, 1, 14, 0],
        'circle-emissive-strength': 1,
      },
    },
    {
      id: 'waypoint-dots',
      type: 'circle',
      source: 'ex-waypoints',
      ...slot,
      paint: {
        'circle-color': '#0a1628',
        'circle-radius': 8,
        'circle-stroke-color': get('color'),
        'circle-stroke-width': 1.5,
        'circle-opacity': ['case', get('selected'), 0.95, 0.6],
        'circle-stroke-opacity': ['case', get('selected'), 1, 0.6],
        'circle-emissive-strength': 1,
      },
    },
    {
      id: 'waypoint-numbers',
      type: 'symbol',
      source: 'ex-waypoints',
      ...slot,
      layout: { 'text-field': ['to-string', get('index')], 'text-font': FONT, 'text-size': 10, 'text-allow-overlap': true },
      paint: { 'text-color': '#ffffff', 'text-opacity': ['case', get('selected'), 1, 0.7], 'text-emissive-strength': 1 },
    },
    {
      id: 'ship-labels',
      type: 'symbol',
      source: 'ex-markers',
      ...slot,
      layout: {
        // Names only when zoomed out, so a crowded group stays readable; speed and heading once the ships are big enough.
        'text-field': ['step', ['zoom'], ['get', 'name'], 11.5, ['format', ['get', 'name'], {}, '\n', {}, ['get', 'info'], { 'font-scale': 0.78, 'text-color': '#d6e6ff' }]],
        'symbol-sort-key': ['case', get('selected'), 0, 1],
        'text-padding': 6,
        'text-font': FONT,
        'text-size': 13,
        'text-line-height': 1.25,
        'text-offset': [0, 1.5],
        'text-anchor': 'top',
        'text-allow-overlap': false,
      },
      paint: {
        'text-color': get('color'),
        'text-halo-color': 'rgba(6,12,24,0.9)',
        'text-halo-width': 1.6,
        'text-emissive-strength': 1,
      },
    },
  ] as unknown as Layer[];
}

/** Add whatever of our sources and layers the current style is missing. Call after every style load. */
export function installLayers(map: MapboxMap): void {
  for (const [id, source] of Object.entries(SOURCES)) {
    if (!map.getSource(id)) map.addSource(id, source);
  }
  for (const layer of layers()) {
    if (!map.getLayer(layer.id)) map.addLayer(layer);
  }
}

/** Non-Standard styles need a sky and some haze to look like open water rather than a flat texture. */
export function installAtmosphere(map: MapboxMap, standard: boolean): void {
  if (standard) return;
  if (!map.getLayer('ex-sky')) {
    map.addLayer({
      id: 'ex-sky',
      type: 'sky',
      paint: { 'sky-type': 'atmosphere', 'sky-atmosphere-sun': [0, 70], 'sky-atmosphere-sun-intensity': 12 },
    } as Layer);
  }
  map.setFog({ range: [0.5, 9], color: 'rgb(190, 210, 235)', 'high-color': 'rgb(70, 120, 200)', 'horizon-blend': 0.04, 'space-color': 'rgb(8, 14, 30)', 'star-intensity': 0 });
}

function setData(map: MapboxMap, id: string, data: unknown): void {
  (map.getSource(id) as GeoJSONSource | undefined)?.setData(data as never);
}

export function setLightLevel(map: MapboxMap, preset: LightPreset): void {
  const level = LIGHT_LEVEL[preset];
  if (map.getLayer('ship-lights')) map.setPaintProperty('ship-lights', 'fill-extrusion-opacity', level.pillars);
  if (map.getLayer('light-glows')) map.setPaintProperty('light-glows', 'circle-opacity', level.glow);
}

export function setFrameData(map: MapboxMap, f: FrameData): void {
  setData(map, 'ex-halos', f.halos);
  setData(map, 'ex-foam', f.foam);
  setData(map, 'ex-lights', f.lights);
  setData(map, 'ex-glows', f.glows);
  setData(map, 'ex-trails', f.trails);
  setData(map, 'ex-hulls', f.hulls);
  setData(map, 'ex-parts', f.parts);
  setData(map, 'ex-overlays', f.overlays);
  setData(map, 'ex-markers', f.markers);
}

export function setStaticData(map: MapboxMap, d: StaticData): void {
  setData(map, 'ex-routes', d.routes);
  setData(map, 'ex-waypoints', d.waypoints);
}

export function setLabelsVisible(map: MapboxMap, visible: boolean): void {
  if (map.getLayer('ship-labels')) map.setLayoutProperty('ship-labels', 'visibility', visible ? 'visible' : 'none');
}
