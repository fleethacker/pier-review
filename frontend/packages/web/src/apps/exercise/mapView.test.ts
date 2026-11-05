// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExerciseController } from './controller';
import { installLayers, LIGHT_LEVEL, PICK_LAYERS } from './mapLayers';
import { ExerciseMapView } from './mapView';
import type { MapProblem } from './mapView';
import { PRESET_SCENARIOS } from './scenarios';

// Running a red-team batch inside a test is slow when the whole suite runs at once.
vi.setConfig({ testTimeout: 60_000 });

type Handler = (e?: unknown) => void;

const glow = (level: number) => ['max', ['get', 'minGlow'], level];

class FakeMap {
  static instances: FakeMap[] = [];
  handlers = new Map<string, Handler[]>();
  sources = new Map<string, { data: unknown; setData: (d: unknown) => void }>();
  layers = new Map<string, { id: string }>();
  config: Record<string, unknown> = {};
  layout: Record<string, unknown> = {};
  paint: Record<string, unknown> = {};
  bearing = -25;
  jumps: Record<string, unknown>[] = [];
  fits: { bounds: unknown; options: Record<string, unknown> }[] = [];
  styleUrls: string[] = [];
  hits: { properties: Record<string, unknown> }[] = [];
  listeners: Record<string, ((e: Event) => void)[]> = {};
  canvas = {
    style: { cursor: '' },
    addEventListener: (type: string, fn: (e: Event) => void) => (this.listeners[type] ??= []).push(fn),
    removeEventListener: (type: string, fn: (e: Event) => void) => (this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn)),
  };
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
  setPaintProperty(id: string, key: string, value: unknown) {
    this.paint[`${id}.${key}`] = value;
  }
  setFog() {}
  setStyle(url: string) {
    this.styleUrls.push(url);
    this.sources.clear();
    this.layers.clear();
  }
  jumpTo(o: Record<string, unknown>) {
    this.jumps.push(o);
    if (typeof o.bearing === 'number') this.bearing = o.bearing;
  }
  fitBounds(bounds: unknown, options: Record<string, unknown>) {
    this.fits.push({ bounds, options });
  }
  getPitch() {
    return 60;
  }
  getBearing() {
    return this.bearing;
  }
  getCanvas() {
    return this.canvas;
  }
  /** What a query over the waypoint or handle layers finds, by layer. Ships are `hits`. */
  layerHits: Record<string, { properties: Record<string, unknown> }[]> = {};
  queryRenderedFeatures(_point: unknown, options?: { layers?: string[] }) {
    const layers = options?.layers ?? [];
    return layers.every((l) => PICK_LAYERS.includes(l)) ? this.hits : layers.flatMap((l) => this.layerHits[l] ?? []);
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

/** A hand-cranked animation frame, so orbiting can be stepped deterministically. */
function fakeFrames() {
  let next = 1;
  const pending = new Map<number, (ms: number) => void>();
  vi.stubGlobal('requestAnimationFrame', (cb: (ms: number) => void) => {
    pending.set(next, cb);
    return next++;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => pending.delete(id));
  return {
    pending: () => pending.size,
    run(ms: number) {
      const callbacks = [...pending.values()];
      pending.clear();
      callbacks.forEach((cb) => cb(ms));
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('ExerciseMapView', () => {
  it('creates the map with the token, the scenario center, opening high for the fly-in', () => {
    const { map } = setup();
    expect((fakeMapbox as unknown as { accessToken: string }).accessToken).toBe('pk.test.token');
    expect(map.options.style).toBe('mapbox://styles/mapbox/standard');
    expect(map.options.center).toEqual([PRESET_SCENARIOS[0].center.lon, PRESET_SCENARIOS[0].center.lat]);
    expect(map.options.zoom).toBeLessThan(10);
    expect(map.options.projection).toBe('mercator');
  });

  it('draws nothing until the style has loaded, then installs every layer and fills them', () => {
    const { map, data } = setup();
    expect(map.layers.size).toBe(0);
    map.fire('style.load');
    expect(map.sources.size).toBe(15);
    expect(map.layers.size).toBeGreaterThanOrEqual(10);
    for (const id of PICK_LAYERS) expect(map.getLayer(id), id).toBeDefined();
    expect(data('ex-hulls')).toHaveLength(15);
    expect(data('ex-markers')).toHaveLength(5);
    expect(data('ex-foam')).toHaveLength(5);
    expect(data('ex-lights').length).toBeGreaterThan(20);
    expect(data('ex-routes').length).toBeGreaterThan(0);
    expect(map.paint['ship-lights.fill-extrusion-opacity']).toBe(LIGHT_LEVEL.dusk.pillars);
    expect(map.paint['light-glows.circle-opacity']).toEqual(glow(LIGHT_LEVEL.dusk.glow));
  });

  it('glides in to the main group on first load, tilted down on it, leaving distant ships out of frame', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    expect(map.fits).toHaveLength(1);
    expect(map.fits[0].options).toMatchObject({ duration: 3800, pitch: 62 });
    const [[, south], [, north]] = map.fits[0].bounds as [[number, number], [number, number]];
    const merchant = controller.currentStates()[4];
    expect(merchant.lat).toBeGreaterThan(north);
    expect(south).toBeLessThanOrEqual(north);
  });

  it('installing layers twice does not duplicate them', () => {
    const { map } = setup();
    map.fire('style.load');
    const before = map.layers.size;
    installLayers(map as never);
    expect(map.layers.size).toBe(before);
  });

  it('applies the light preset, and the light level for the ship lights, per time of day', () => {
    const { map, controller } = setup({ ...PRESET_SCENARIOS[1] });
    map.fire('style.load');
    expect(map.config.lightPreset).toBe('night');
    expect(map.paint['light-glows.circle-opacity']).toEqual(glow(LIGHT_LEVEL.night.glow));
    controller.patchScenario({ lightPreset: 'dawn' });
    expect(map.config.lightPreset).toBe('dawn');
    expect(map.paint['light-glows.circle-opacity']).toEqual(glow(LIGHT_LEVEL.dawn.glow));

    // Non-Standard styles have no light preset to set, but the ship lights still follow the time of day.
    controller.setMapStyle('dark');
    map.fire('style.load');
    controller.patchScenario({ lightPreset: 'day' });
    expect(map.config.lightPreset).toBe('dawn');
    expect(map.paint['light-glows.circle-opacity']).toEqual(glow(0));
    expect(map.paint['ship-lights.fill-extrusion-opacity']).toBe(LIGHT_LEVEL.day.pillars);
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

  it('orbits the whole group when nothing is selected, turning even while the clock is paused', () => {
    const frames = fakeFrames();
    const { map, controller } = setup();
    map.fire('style.load');
    controller.setFollow('orbit');
    expect(controller.state.get().follow).toBe('orbit');
    expect(frames.pending()).toBe(1);
    map.jumps.length = 0;
    frames.run(1000);
    frames.run(3000);
    expect(map.jumps.at(-1)).toEqual({ bearing: -25 + 5 * 0.1 });
    expect(map.jumps[0]).toEqual({ bearing: -25 });
    controller.seek(300);
    expect(map.jumps.some((j) => Array.isArray(j.center))).toBe(true);
  });

  it('orbits the selected ship, and clicking empty water does not stop an orbit', () => {
    fakeFrames();
    const { map, controller } = setup();
    map.fire('style.load');
    controller.select('cvn1');
    controller.setFollow('orbit');
    map.jumps.length = 0;
    controller.seek(600);
    const [state] = controller.currentStates();
    expect(map.jumps.at(-1)).toEqual({ center: [state.lon, state.lat] });
    map.hits = [];
    map.fire('click', { point: { x: 1, y: 1 }, lngLat: { lng: -62, lat: 33 } });
    expect(controller.state.get().selectedId).toBeNull();
    expect(controller.state.get().follow).toBe('orbit');
  });

  it('does not rebuild the ships for state the map does not show, but does when something it shows changes', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    let writes = 0;
    for (const id of ['ex-hulls', 'ex-markers', 'ex-bursts']) {
      const src = map.getSource(id)!;
      const original = src.setData;
      src.setData = (d) => {
        writes++;
        original(d);
      };
    }
    controller.notify('hello');
    controller.toggleRedTeam(true);
    controller.state.set((s) => ({ mc: { ...s.mc, status: 'running', done: 5, total: 10 } }));
    expect(writes).toBe(0);
    controller.select('cvn1');
    expect(writes).toBe(3);
    controller.setView({ shipScale: 6 });
    expect(writes).toBe(6);
    controller.seek(100);
    expect(writes).toBe(9);
  });

  it('stops turning when orbit ends or the view is disposed', () => {
    const frames = fakeFrames();
    const { map, controller, view } = setup();
    map.fire('style.load');
    controller.setFollow('orbit');
    controller.setFollow('off');
    expect(frames.pending()).toBe(0);
    controller.setFollow('orbit');
    expect(frames.pending()).toBe(1);
    view.dispose();
    expect(frames.pending()).toBe(0);
  });

  it('frames the main group when a scenario is loaded, and every ship when Fit all is pressed', () => {
    const { map, controller } = setup();
    map.fire('style.load');
    controller.loadPreset('surface-encounter');
    expect(map.fits).toHaveLength(2);
    expect(map.fits[1].options.duration).toBe(1200);
    controller.fitAll();
    expect(map.fits).toHaveLength(3);
    const span = (f: { bounds: unknown }) => {
      const [[w], [e]] = f.bounds as [[number, number], [number, number]];
      return e - w;
    };
    expect(span(map.fits[2])).toBeGreaterThan(span(map.fits[1]) * 1.5);
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
    expect(map.canvas.style.cursor).toBe('grab'); // at the start a ship can be dragged
    controller.seek(120);
    map.fire('mousemove', { point: { x: 1, y: 1 } });
    expect(map.canvas.style.cursor).toBe('pointer'); // later it cannot
    map.hits = [];
    map.fire('mousemove', { point: { x: 1, y: 1 } });
    expect(map.canvas.style.cursor).toBe('');
    controller.select('cvn1');
    controller.setPlacing(true);
    map.hits = [{ properties: { id: 'cvn1' } }];
    map.fire('mousemove', { point: { x: 1, y: 1 } });
    expect(map.canvas.style.cursor).toBe('crosshair');
  });

  describe('dragging', () => {
    const at = (x: number, y: number, lng = -62, lat = 33) => ({ point: { x, y }, lngLat: { lng, lat }, originalEvent: { button: 0 }, preventDefault: vi.fn() });
    const cvnRoute = (c: ExerciseController) => {
      const b = c.state.get().scenario.units.find((u) => u.id === 'cvn1')!.behavior;
      return b.type === 'route' ? b.waypoints : [];
    };
    const start = (c: ExerciseController, id: string) => c.state.get().scenario.units.find((u) => u.id === id)!.start;

    it('moves a ship to where it is dropped, and does not select what was only dragged over', () => {
      const { map, controller } = setup();
      map.fire('style.load');
      map.hits = [{ properties: { id: 'cvn1' } }];
      const down = at(10, 10, -62, 33);
      map.fire('mousedown', down);
      expect(down.preventDefault).toHaveBeenCalled();
      map.fire('mousemove', at(40, 40, -61.9, 33.1));
      expect(map.canvas.style.cursor).toBe('grabbing');
      const ghost = (map.getSource('ex-drag')!.data as { features: { geometry: { type: string; coordinates: unknown } }[] }).features;
      expect(ghost.map((f) => f.geometry.type)).toEqual(['LineString', 'Point']);
      expect(ghost[1].geometry.coordinates).toEqual([-61.9, 33.1]);
      expect(start(controller, 'cvn1')).not.toMatchObject({ lon: -61.9 }); // nothing changes until it is dropped
      map.fire('mouseup', at(40, 40, -61.9, 33.1));
      expect(start(controller, 'cvn1')).toEqual({ lon: -61.9, lat: 33.1 });
      expect(controller.state.get().selectedId).toBe('cvn1');
      expect((map.getSource('ex-drag')!.data as { features: unknown[] }).features).toEqual([]);
      expect(map.canvas.style.cursor).toBe('');
      // The click that follows the drop does not change the selection.
      map.hits = [];
      map.fire('click', at(40, 40, -61.9, 33.1));
      expect(controller.state.get().selectedId).toBe('cvn1');
      map.fire('click', at(40, 40, -61.9, 33.1));
      expect(controller.state.get().selectedId).toBeNull();
    });

    it('treats a press that barely moves as a click', () => {
      const { map, controller } = setup();
      map.fire('style.load');
      map.hits = [{ properties: { id: 'cvn1' } }];
      const before = start(controller, 'cvn1');
      map.fire('mousedown', at(10, 10));
      map.fire('mousemove', at(12, 11, -61.99, 33.01));
      map.fire('mouseup', at(12, 11, -61.99, 33.01));
      expect(start(controller, 'cvn1')).toEqual(before);
      map.fire('click', at(12, 11));
      expect(controller.state.get().selectedId).toBe('cvn1');
    });

    it('does not move ships once the clock has moved, or launched units, or while a run is replayed or waypoints are being placed', () => {
      const { map, controller } = setup(PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!);
      map.fire('style.load');
      const tryDrag = (id: string) => {
        map.hits = [{ properties: { id } }];
        const down = at(10, 10);
        map.fire('mousedown', down);
        map.fire('mousemove', at(60, 60, -61.5, 33.5));
        map.fire('mouseup', at(60, 60, -61.5, 33.5));
        return down.preventDefault.mock.calls.length > 0;
      };
      expect(tryDrag('m1')).toBe(false); // a missile is launched, not placed
      controller.seek(30);
      expect(tryDrag('cvn1')).toBe(false);
      controller.seek(0);
      controller.select('cvn1');
      controller.setPlacing(true);
      expect(controller.state.get().placing).toBe(true);
      expect(tryDrag('cvn1')).toBe(false);
      controller.setPlacing(false);
      expect(tryDrag('cvn1')).toBe(true);
      controller.state.set({ replay: { run: 1, groupLabel: 'All runs', outcomeLabel: null, values: [] } });
      expect(tryDrag('cvn1')).toBe(false);
    });

    it('drags a waypoint of the selected route, and leaves other routes alone', () => {
      const { map, controller } = setup();
      map.fire('style.load');
      controller.select('cvn1');
      const wp0 = cvnRoute(controller)[0];
      map.layerHits['waypoint-dots'] = [{ properties: { id: 'cvn1', n: 0, selected: true } }];
      map.fire('mousemove', at(5, 5));
      expect(map.canvas.style.cursor).toBe('grab');
      map.fire('mousedown', at(5, 5, wp0.lon, wp0.lat));
      map.fire('mousemove', at(50, 5, -61.8, 33.2));
      map.fire('mouseup', at(50, 5, -61.8, 33.2));
      expect(cvnRoute(controller)[0]).toMatchObject({ lon: -61.8, lat: 33.2 });
      expect(cvnRoute(controller)).toHaveLength(1 + (cvnRoute(controller).length - 1));
      // A waypoint that belongs to a route that is not selected is not draggable.
      map.layerHits['waypoint-dots'] = [{ properties: { id: 'ddg1', n: 0, selected: false } }];
      const down = at(5, 5);
      map.fire('mousedown', down);
      expect(down.preventDefault).not.toHaveBeenCalled();
    });

    it('adds a waypoint by dragging the middle of a leg out', () => {
      const { map, controller } = setup();
      map.fire('style.load');
      controller.select('cvn1');
      const n = cvnRoute(controller).length;
      map.layerHits['handle-dots'] = [{ properties: { id: 'cvn1', insertAt: 0 } }];
      map.fire('mousemove', at(5, 5));
      expect(map.canvas.style.cursor).toBe('copy');
      map.fire('mousedown', at(5, 5, -62, 33));
      map.fire('mousemove', at(60, 5, -61.7, 33.3));
      map.fire('mouseup', at(60, 5, -61.7, 33.3));
      expect(cvnRoute(controller)).toHaveLength(n + 1);
      expect(cvnRoute(controller)[0]).toMatchObject({ lon: -61.7, lat: 33.3 });
    });

    it('drops nothing when Escape is pressed, or the button is let go outside the map', () => {
      const { map, controller } = setup();
      map.fire('style.load');
      map.hits = [{ properties: { id: 'cvn1' } }];
      const before = start(controller, 'cvn1');
      map.fire('mousedown', at(10, 10));
      map.fire('mousemove', at(60, 60, -61.5, 33.5));
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      map.fire('mouseup', at(60, 60, -61.5, 33.5));
      expect(start(controller, 'cvn1')).toEqual(before);
      map.fire('mousedown', at(10, 10));
      map.fire('mousemove', at(60, 60, -61.5, 33.5));
      window.dispatchEvent(new MouseEvent('mouseup'));
      expect(start(controller, 'cvn1')).toEqual(before);
      expect((map.getSource('ex-drag')!.data as { features: unknown[] }).features).toEqual([]);
    });

    it('removes a waypoint on right-click, but never the last one', () => {
      const { map, controller } = setup();
      map.fire('style.load');
      controller.select('cvn1');
      controller.addWaypoint('cvn1', { lon: -61.5, lat: 33.2 });
      const n = cvnRoute(controller).length;
      map.layerHits['waypoint-dots'] = [{ properties: { id: 'cvn1', n: 0, selected: true } }];
      const ev = at(5, 5);
      map.fire('contextmenu', ev);
      expect(ev.preventDefault).toHaveBeenCalled();
      expect(cvnRoute(controller)).toHaveLength(n - 1);
      for (let i = cvnRoute(controller).length; i > 1; i--) map.fire('contextmenu', at(5, 5));
      expect(cvnRoute(controller)).toHaveLength(1);
      map.fire('contextmenu', at(5, 5));
      expect(cvnRoute(controller)).toHaveLength(1);
      expect(controller.state.get().notice).toContain('at least one waypoint');
    });

    it('stops listening to the window when the view is disposed', () => {
      const { map, controller, view } = setup();
      map.fire('style.load');
      view.dispose();
      map.hits = [{ properties: { id: 'cvn1' } }];
      const spy = vi.spyOn(controller, 'select');
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      window.dispatchEvent(new MouseEvent('mouseup'));
      expect(spy).not.toHaveBeenCalled();
    });
  });

  it('draws the paths of compared runs, and clears them', async () => {
    const { map, controller, data } = setup(PRESET_SCENARIOS.find((p) => p.id === 'salvo-defense')!);
    map.fire('style.load');
    expect(data('ex-runs')).toEqual([]);
    controller.setRedTeam({ ...controller.redTeamSpec(), runs: 6, sweep: undefined });
    await controller.runRedTeam();
    const outcome = controller.state.get().mc.result!.groups[0].outcomes[0];
    await controller.showRunOverlay(0, outcome.id, outcome.label);
    const features = data('ex-runs');
    expect(features.length).toBeGreaterThan(10);
    expect(features.some((f) => f.properties.weapon === true)).toBe(true);
    expect(features.every((f) => typeof f.properties.hit === 'boolean')).toBe(true);
    controller.clearRunOverlay();
    expect(data('ex-runs')).toEqual([]);
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

  it('reports a lost graphics context, lets the browser restore it, and stops listening on dispose', () => {
    const { map, problems, view } = setup();
    let prevented = false;
    map.listeners.webglcontextlost.forEach((fn) => fn({ preventDefault: () => (prevented = true) } as unknown as Event));
    expect(prevented).toBe(true);
    expect(problems).toHaveLength(1);
    expect(problems[0].kind).toBe('webgl');
    expect(problems[0].message).toContain('reload');
    view.dispose();
    expect(map.listeners.webglcontextlost).toEqual([]);
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
