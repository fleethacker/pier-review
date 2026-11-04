// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExerciseController } from './controller';
import { installLayers, PICK_LAYERS } from './mapLayers';
import { ExerciseMapView } from './mapView';
import type { MapProblem } from './mapView';
import { PRESET_SCENARIOS } from './scenarios';

type Handler = (e?: unknown) => void;

class FakeMap {
  static instances: FakeMap[] = [];
  handlers = new Map<string, Handler[]>();
  sources = new Map<string, { data: unknown; setData: (d: unknown) => void }>();
  layers = new Map<string, { id: string }>();
  config: Record<string, unknown> = {};
  layout: Record<string, unknown> = {};
  jumps: Record<string, unknown>[] = [];
  fits: { bounds: unknown; options: Record<string, unknown> }[] = [];
  styleUrls: string[] = [];
  hits: { properties: Record<string, unknown> }[] = [];
  canvas = { style: { cursor: '' } };
  removed = false;
  resizes = 0;

  constructor(public options: Record<string, unknown>) {
    FakeMap.instances.push(this);
  }
  on(event: string, fn: Handler) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), fn]);
  }
  fire(event: string, payload?: unknown) {
    this.handlers.get(event)?.forEach((h) => h(payload));
  }
  addControl() {}
  addSource(id: string, spec: { data: unknown }) {
    const source = { data: spec.data, setData: (d: unknown) => void (source.data = d) };
    this.sources.set(id, source);
  }
  getSource(id: string) {
    return this.sources.get(id);
  }
  addLayer(layer: { id: string }) {
    this.layers.set(layer.id, layer);
  }
  getLayer(id: string) {
    return this.layers.get(id);
  }
  setLayoutProperty(id: string, key: string, value: unknown) {
    this.layout[`${id}.${key}`] = value;
  }
  setConfigProperty(_fragment: string, key: string, value: unknown) {
    this.config[key] = value;
  }
  setFog() {}
  setStyle(url: string) {
    this.styleUrls.push(url);
    this.sources.clear();
    this.layers.clear();
  }
  jumpTo(o: Record<string, unknown>) {
    this.jumps.push(o);
  }
  fitBounds(bounds: unknown, options: Record<string, unknown>) {
    this.fits.push({ bounds, options });
  }
  getPitch() {
    return 60;
  }
  getBearing() {
    return -25;
  }
  getCanvas() {
    return this.canvas;
  }
  queryRenderedFeatures() {
    return this.hits;
  }
  resize() {
    this.resizes++;
  }
  remove() {
    this.removed = true;
  }
}

const fakeMapbox = {
  accessToken: '',
  Map: FakeMap,
  NavigationControl: class {},
  ScaleControl: class {},
} as unknown as ConstructorParameters<typeof ExerciseMapView>[1];

function setup(initial = PRESET_SCENARIOS[0]) {
  FakeMap.instances.length = 0;
  const controller = new ExerciseController(undefined, initial);
  const problems: MapProblem[] = [];
  const view = new ExerciseMapView(document.createElement('div'), fakeMapbox, 'pk.test.token', controller, (p) => problems.push(p));
  const map = FakeMap.instances[0];
  const data = (id: string) => (map.getSource(id)!.data as { features: { properties: Record<string, unknown>; geometry: { coordinates: unknown } }[] }).features;
  return { controller, view, map, problems, data };
}

afterEach(() => vi.unstubAllGlobals());

describe('ExerciseMapView', () => {
  it('creates the map with the token, the scenario center and a tilted view', () => {
    const { map } = setup();
    expect((fakeMapbox as unknown as { accessToken: string }).accessToken).toBe('pk.test.token');
    expect(map.options.style).toBe('mapbox://styles/mapbox/standard');
    expect(map.options.center).toEqual([PRESET_SCENARIOS[0].center.lon, PRESET_SCENARIOS[0].center.lat]);
    expect(map.options.pitch).toBeGreaterThan(45);
    expect(map.options.projection).toBe('mercator');
  });

  it('draws nothing until the style has loaded, then installs every layer and fills them', () => {
    const { map, data } = setup();
    expect(map.layers.size).toBe(0);
    map.fire('style.load');
    expect(map.sources.size).toBe(8);
    expect(map.layers.size).toBeGreaterThanOrEqual(10);
    for (const id of PICK_LAYERS) expect(map.getLayer(id), id).toBeDefined();
    expect(data('ex-hulls')).toHaveLength(5);
    expect(data('ex-markers')).toHaveLength(5);
    expect(data('ex-routes').length).toBeGreaterThan(0);
    expect(map.fits).toHaveLength(1);
    expect(map.fits[0].options.duration).toBe(0);
  });

  it('installing layers twice does not duplicate them', () => {
    const { map } = setup();
    map.fire('style.load');
    const before = map.layers.size;
    installLayers(map as never);
    expect(map.layers.size).toBe(before);
  });

  it('applies the light preset on Standard styles only', () => {
    const { map, controller } = setup({ ...PRESET_SCENARIOS[1] });
    map.fire('style.load');
    expect(map.config.lightPreset).toBe('dusk');
    controller.patchScenario({ lightPreset: 'night' });
    expect(map.config.lightPreset).toBe('night');

    controller.setMapStyle('dark');
    map.fire('style.load');
    controller.patchScenario({ lightPreset: 'dawn' });
    expect(map.config.lightPreset).toBe('night');
  });

  it('moves the ships as the clock moves', () => {
    const { map, controller, data } = setup();
    map.fire('style.load');
    const first = JSON.stringify(data('ex-hulls')[0].geometry.coordinates);
    controller.seek(1200);
    expect(JSON.stringify(data('ex-hulls')[0].geometry.coordinates)).not.toBe(first);
  });

  it('re-installs on a new style without reframing the camera', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    controller.setMapStyle('satellite-streets');
    expect(map.styleUrls).toEqual(['mapbox://styles/mapbox/satellite-streets-v12']);
    controller.seek(100);
    map.fire('style.load');
    expect(map.layers.size).toBeGreaterThanOrEqual(10);
    expect(map.fits).toHaveLength(1);
  });

  it('reframes when a scenario is loaded or Fit all is pressed', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    controller.loadPreset('formation-drill');
    expect(map.fits).toHaveLength(2);
    expect(map.fits[1].options.duration).toBe(1200);
    controller.fitAll();
    expect(map.fits).toHaveLength(3);
  });

  it('selects the ship that was clicked, and clears the selection when the click hits nothing', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    map.hits = [{ properties: { id: 'ddg1' } }];
    map.fire('click', { point: { x: 1, y: 1 }, lngLat: { lng: -62, lat: 33 } });
    expect(controller.state.get().selectedId).toBe('ddg1');
    map.hits = [];
    map.fire('click', { point: { x: 1, y: 1 }, lngLat: { lng: -62, lat: 33 } });
    expect(controller.state.get().selectedId).toBeNull();
  });

  it('adds a waypoint at the click while placing, and keeps placing', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    controller.select('cvn1');
    controller.setPlacing(true);
    expect(map.canvas.style.cursor).toBe('crosshair');
    map.hits = [{ properties: { id: 'ddg1' } }];
    map.fire('click', { point: { x: 1, y: 1 }, lngLat: { lng: -61.5, lat: 33.2 } });
    const b = controller.state.get().scenario.units.find((u) => u.id === 'cvn1')!.behavior;
    expect(b.type === 'route' && b.waypoints.at(-1)).toMatchObject({ lon: -61.5, lat: 33.2 });
    expect(controller.state.get().selectedId).toBe('cvn1');
    expect(controller.state.get().placing).toBe(true);
  });

  it('keeps the selected ship centered when following, and points along its heading when chasing', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    controller.select('cvn1');
    controller.setFollow('follow');
    map.jumps.length = 0;
    controller.seek(600);
    const [state] = controller.currentStates();
    expect(map.jumps.at(-1)).toEqual({ center: [state.lon, state.lat] });
    controller.setFollow('chase');
    controller.seek(700);
    const [later] = controller.currentStates();
    expect(map.jumps.at(-1)).toEqual({ center: [later.lon, later.lat], bearing: later.headingDeg });
  });

  it('shows the pointer over a ship, and not while placing', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    map.hits = [{ properties: { id: 'cvn1' } }];
    map.fire('mousemove', { point: { x: 1, y: 1 } });
    expect(map.canvas.style.cursor).toBe('pointer');
    map.hits = [];
    map.fire('mousemove', { point: { x: 1, y: 1 } });
    expect(map.canvas.style.cursor).toBe('');
    controller.select('cvn1');
    controller.setPlacing(true);
    map.hits = [{ properties: { id: 'cvn1' } }];
    map.fire('mousemove', { point: { x: 1, y: 1 } });
    expect(map.canvas.style.cursor).toBe('crosshair');
  });

  it('hides ship names on request', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    controller.setView({ showLabels: false });
    expect(map.layout['ship-labels.visibility']).toBe('none');
  });

  it('reports a rejected token every time and a refused request once', () => {
    const { map, problems } = setup();
    map.fire('error', { error: { status: 401 } });
    expect(problems.map((p) => p.kind)).toEqual(['token']);
    map.fire('error', { error: { status: 429 } });
    map.fire('error', { error: { status: 429 } });
    map.fire('error', { error: { status: 404 } });
    expect(problems.map((p) => p.kind)).toEqual(['token', 'quota']);
  });

  it('stops listening and removes the map on dispose', () => {
    const { map, controller, view } = setup();
    map.fire('style.load');
    view.dispose();
    expect(map.removed).toBe(true);
    expect(() => controller.seek(10)).not.toThrow();
    expect(() => controller.setView({ trailS: 0 })).not.toThrow();
  });

  it('resizes with its container', () => {
    const observed: { cb: () => void }[] = [];
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(cb: () => void) {
          observed.push({ cb });
        }
        observe() {}
        disconnect() {}
      },
    );
    const { map } = setup();
    observed[0].cb();
    expect(map.resizes).toBe(1);
  });
});
