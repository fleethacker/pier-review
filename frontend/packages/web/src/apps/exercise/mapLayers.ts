import type { AnyLayer as Layer, AnySourceData as Source, GeoJSONSource, Map as MapboxMap } from 'mapbox-gl';
import type { FrameData, RunTrack, StaticData } from './scene';
import type { LightPreset } from './types';

const empty = { type: 'FeatureCollection', features: [] } as const;

/** Layers a click can pick a ship from, topmost first. */
export const PICK_LAYERS = ['ship-markers', 'ship-parts', 'ship-hulls', 'ship-halos'];
/** Layers of the selected route's editing handles: its waypoints, and the midpoints of its legs. */
export const WAYPOINT_LAYER = 'waypoint-dots';
export const HANDLE_LAYER = 'handle-dots';

/** Source id to the data it carries. Every source starts empty and is filled by `setFrameData` and `setStaticData`. */
const SOURCES: Record<string, Source> = {
  'ex-halos': { type: 'geojson', data: empty },
  'ex-foam': { type: 'geojson', data: empty },
  'ex-lights': { type: 'geojson', data: empty },
  'ex-glows': { type: 'geojson', data: empty },
  'ex-bursts': { type: 'geojson', data: empty },
  'ex-routes': { type: 'geojson', data: empty },
  'ex-waypoints': { type: 'geojson', data: empty },
  'ex-trails': { type: 'geojson', data: empty, lineMetrics: true },
  'ex-hulls': { type: 'geojson', data: empty },
  'ex-parts': { type: 'geojson', data: empty },
  'ex-overlays': { type: 'geojson', data: empty },
  'ex-markers': { type: 'geojson', data: empty },
  'ex-handles': { type: 'geojson', data: empty },
  'ex-runs': { type: 'geojson', data: empty },
  'ex-drag': { type: 'geojson', data: empty },
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

/** A light's glow: the time-of-day level, but never less than the light's own minimum (a missile's exhaust glows by day). */
const glowOpacity = (level: number) => ['max', ['get', 'minGlow'], level];

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
      id: 'run-tracks',
      type: 'line',
      source: 'ex-runs',
      ...slot,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['case', get('hit'), '#ff5a4a', '#4adf9a'],
        'line-width': ['case', get('weapon'), 1, 2],
        'line-opacity': ['case', get('weapon'), 0.4, 0.55],
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
      id: 'overlay-strike',
      type: 'line',
      source: 'ex-overlays',
      ...slot,
      filter: ['==', get('kind'), 'strike'],
      paint: { 'line-color': get('color'), 'line-width': 1, 'line-opacity': 0.55, 'line-dasharray': [1, 2], 'line-emissive-strength': 1 },
    },
    {
      id: 'overlay-danger',
      type: 'line',
      source: 'ex-overlays',
      ...slot,
      filter: ['==', get('kind'), 'danger'],
      paint: { 'line-color': get('color'), 'line-width': 1, 'line-opacity': 0.35, 'line-emissive-strength': 1 },
    },
    {
      id: 'overlay-defence',
      type: 'line',
      source: 'ex-overlays',
      ...slot,
      filter: ['==', get('kind'), 'defence'],
      paint: { 'line-color': get('color'), 'line-width': 1.2, 'line-opacity': 0.8, 'line-dasharray': [2, 2], 'line-emissive-strength': 1 },
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
        'circle-opacity': glowOpacity(LIGHT_LEVEL.day.glow),
        'circle-emissive-strength': 1,
      },
    },
    {
      id: 'burst-glows',
      type: 'circle',
      source: 'ex-bursts',
      ...slot,
      paint: {
        'circle-color': get('color'),
        'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 0, ['*', get('sizeM'), GLOW_PX0], 24, ['*', get('sizeM'), GLOW_PX0 * 16777216]],
        'circle-blur': 0.9,
        'circle-opacity': get('opacity'),
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
        'circle-radius': ['case', get('selected'), 8, get('r')],
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
      id: 'handle-dots',
      type: 'circle',
      source: 'ex-handles',
      ...slot,
      paint: {
        'circle-color': '#0a1628',
        'circle-radius': 4.5,
        'circle-stroke-color': get('color'),
        'circle-stroke-width': 1.2,
        'circle-opacity': 0.7,
        'circle-stroke-opacity': 0.9,
        'circle-emissive-strength': 1,
      },
    },
    {
      id: 'drag-line',
      type: 'line',
      source: 'ex-drag',
      ...slot,
      filter: ['==', ['geometry-type'], 'LineString'],
      paint: { 'line-color': '#ffffff', 'line-width': 1.5, 'line-opacity': 0.8, 'line-dasharray': [2, 2], 'line-emissive-strength': 1 },
    },
    {
      id: 'drag-dot',
      type: 'circle',
      source: 'ex-drag',
      ...slot,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-color': '#ffffff', 'circle-radius': 7, 'circle-opacity': 0.35, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2, 'circle-emissive-strength': 1 },
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
  if (map.getLayer('light-glows')) map.setPaintProperty('light-glows', 'circle-opacity', glowOpacity(level.glow) as never);
}

export function setFrameData(map: MapboxMap, f: FrameData): void {
  setData(map, 'ex-halos', f.halos);
  setData(map, 'ex-foam', f.foam);
  setData(map, 'ex-lights', f.lights);
  setData(map, 'ex-glows', f.glows);
  setData(map, 'ex-bursts', f.bursts);
  setData(map, 'ex-trails', f.trails);
  setData(map, 'ex-hulls', f.hulls);
  setData(map, 'ex-parts', f.parts);
  setData(map, 'ex-overlays', f.overlays);
  setData(map, 'ex-markers', f.markers);
}

export function setStaticData(map: MapboxMap, d: StaticData): void {
  setData(map, 'ex-routes', d.routes);
  setData(map, 'ex-waypoints', d.waypoints);
  setData(map, 'ex-handles', d.handles);
}

/** The preview while something is being dragged: a dashed line from where it was to the cursor, and a ring at the cursor. Null clears it. */
export function setDragGhost(map: MapboxMap, ghost: { from: [number, number]; to: [number, number] } | null): void {
  setData(
    map,
    'ex-drag',
    ghost
      ? {
          type: 'FeatureCollection',
          features: [
            { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [ghost.from, ghost.to] } },
            { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: ghost.to } },
          ],
        }
      : empty,
  );
}

/** Paths of several runs of a red-team batch, to compare them on the map. */
export function setRunTracks(map: MapboxMap, tracks: RunTrack[]): void {
  setData(map, 'ex-runs', {
    type: 'FeatureCollection',
    features: tracks.map((t) => ({ type: 'Feature', properties: { hit: t.hit, weapon: t.weapon }, geometry: { type: 'LineString', coordinates: t.coords } })),
  });
}

export function setLabelsVisible(map: MapboxMap, visible: boolean): void {
  if (map.getLayer('ship-labels')) map.setLayoutProperty('ship-labels', 'visibility', visible ? 'visible' : 'none');
}
