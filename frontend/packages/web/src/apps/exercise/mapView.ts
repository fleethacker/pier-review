import type { Map as MapboxMap, MapMouseEvent } from 'mapbox-gl';
import type { ExerciseController, ExerciseState } from './controller';
import { installAtmosphere, installLayers, PICK_LAYERS, setFrameData, setLabelsVisible, setLightLevel, setStaticData } from './mapLayers';
import { styleById } from './mapStyles';
import { boundsOf, buildFrameData, buildStaticData, groupStates } from './scene';
import type { FollowMode } from './controller';
import { statesAt } from './sim';

type MapboxModule = typeof import('mapbox-gl').default;

export interface MapProblem {
  /** 'token' means nothing will load until the token changes; 'quota' means Mapbox is refusing some requests. */
  kind: 'token' | 'quota';
  message: string;
}

const START_PITCH = 62;
const START_BEARING = -25;
const INTRO_MS = 3800;
const ORBIT_DEG_PER_S = 5;

/** Draws the running exercise on a Mapbox map and turns map clicks into controller actions. No React in here. */
export class ExerciseMapView {
  readonly map: MapboxMap;
  private styleReady = false;
  /** Set once the first style has loaded and the camera has framed the ships, so a style switch does not reframe. */
  private framed = false;
  private prev: ExerciseState;
  private offStore: () => void;
  private offClock: () => void;
  private resizer: ResizeObserver | null = null;

  constructor(
    container: HTMLElement,
    mapbox: MapboxModule,
    token: string,
    private readonly controller: ExerciseController,
    private readonly onProblem: (problem: MapProblem) => void,
  ) {
    const state = controller.state.get();
    this.prev = state;
    mapbox.accessToken = token;
    this.map = new mapbox.Map({
      container,
      style: styleById(state.mapStyle).url,
      center: [state.scenario.center.lon, state.scenario.center.lat],
      zoom: 8.2,
      pitch: 28,
      bearing: 30,
      antialias: true,
      projection: 'mercator',
      maxPitch: 85,
    });
    this.map.addControl(new mapbox.NavigationControl({ visualizePitch: true }), 'bottom-right');
    this.map.addControl(new mapbox.ScaleControl({ unit: 'nautical' }), 'bottom-left');

    this.map.on('style.load', this.onStyleLoad);
    this.map.on('click', this.onClick);
    this.map.on('mousemove', this.onMouseMove);
    this.map.on('error', this.onError);
    if (typeof ResizeObserver !== 'undefined') {
      this.resizer = new ResizeObserver(() => this.map.resize());
      this.resizer.observe(container);
    }
    this.offStore = controller.state.subscribe(this.onStore);
    this.offClock = controller.clock.subscribe(this.draw);
  }

  dispose(): void {
    this.offStore();
    this.offClock();
    cancelAnimationFrame(this.orbiting);
    this.resizer?.disconnect();
    this.map.remove();
  }

  private onStyleLoad = () => {
    const state = this.controller.state.get();
    const style = styleById(state.mapStyle);
    installLayers(this.map);
    installAtmosphere(this.map, style.standard);
    if (style.standard) {
      this.map.setConfigProperty('basemap', 'lightPreset', state.active.scenario.lightPreset);
      for (const key of ['showPointOfInterestLabels', 'showTransitLabels', 'showRoadLabels']) {
        this.map.setConfigProperty('basemap', key, false);
      }
    }
    this.styleReady = true;
    setLightLevel(this.map, state.active.scenario.lightPreset);
    setLabelsVisible(this.map, state.view.showLabels);
    this.refreshStatic();
    this.draw();
    if (!this.framed) {
      this.framed = true;
      // Open high and tilted down, then glide in to the main group so the ships are big enough to see in 3D.
      this.fitAll(true, { pitch: START_PITCH, bearing: START_BEARING, duration: INTRO_MS, group: true });
    }
  };

  private quotaReported = false;

  private onError = (e: { error?: { message?: string; status?: number } }) => {
    const status = e.error?.status;
    if (status === 401 || status === 403) {
      this.onProblem({ kind: 'token', message: 'Mapbox rejected the access token. Check that it is a valid public token (pk.…) with style access.' });
    } else if (status === 429 && !this.quotaReported) {
      this.quotaReported = true;
      this.onProblem({
        kind: 'quota',
        message: 'Mapbox is refusing some map requests for this token (rate limit or plan quota), so parts of the map may be blank. Try another map style, or check the token\'s usage at account.mapbox.com.',
      });
    }
  };

  private onStore = () => {
    const now = this.controller.state.get();
    const was = this.prev;
    this.prev = now;
    if (now.mapStyle !== was.mapStyle) {
      this.styleReady = false;
      this.map.setStyle(styleById(now.mapStyle).url);
      return;
    }
    if (!this.styleReady) return;
    if (now.active.scenario.lightPreset !== was.active.scenario.lightPreset) {
      setLightLevel(this.map, now.active.scenario.lightPreset);
      if (styleById(now.mapStyle).standard) this.map.setConfigProperty('basemap', 'lightPreset', now.active.scenario.lightPreset);
    }
    if (now.view.showLabels !== was.view.showLabels) setLabelsVisible(this.map, now.view.showLabels);
    if (
      now.active !== was.active ||
      now.selectedId !== was.selectedId ||
      now.view.showRoutes !== was.view.showRoutes
    ) {
      this.refreshStatic();
    }
    if (now.scenarioRevision !== was.scenarioRevision) this.fitAll(true, { group: true });
    else if (now.fitRevision !== was.fitRevision) this.fitAll(true);
    if (now.follow !== was.follow) this.setOrbiting(now.follow);
    this.map.getCanvas().style.cursor = now.placing ? 'crosshair' : '';
    this.draw();
  };

  private refreshStatic(): void {
    const s = this.controller.state.get();
    setStaticData(this.map, buildStaticData(s.active.scenario, s.view, s.selectedId));
  }

  private draw = () => {
    if (!this.styleReady) return;
    const s = this.controller.state.get();
    const t = this.controller.clock.timeS;
    setFrameData(this.map, buildFrameData(s.active.scenario, s.active.trajectory, t, s.view, s.selectedId));
    this.keepCentered(s.follow, s.selectedId, t);
  };

  private orbiting = 0;
  private lastOrbitMs = 0;

  /** Orbiting turns the camera even while the clock is paused, so it runs on its own frame loop. */
  private setOrbiting(follow: FollowMode): void {
    cancelAnimationFrame(this.orbiting);
    this.orbiting = 0;
    if (follow !== 'orbit') return;
    this.lastOrbitMs = 0;
    const step = (ms: number) => {
      const dt = this.lastOrbitMs ? Math.min((ms - this.lastOrbitMs) / 1000, 0.1) : 0;
      this.lastOrbitMs = ms;
      this.map.jumpTo({ bearing: this.map.getBearing() + ORBIT_DEG_PER_S * dt });
      this.orbiting = requestAnimationFrame(step);
    };
    this.orbiting = requestAnimationFrame(step);
  }

  private keepCentered(follow: FollowMode, selectedId: string | null, t: number): void {
    if (follow === 'off') return;
    const { active } = this.controller.state.get();
    const states = statesAt(active.trajectory, t);
    const i = selectedId ? active.trajectory.unitIds.indexOf(selectedId) : -1;
    if (i >= 0) {
      const st = states[i];
      this.map.jumpTo(follow === 'chase' ? { center: [st.lon, st.lat], bearing: st.headingDeg } : { center: [st.lon, st.lat] });
      return;
    }
    const b = boundsOf(states);
    if (follow === 'orbit' && b) this.map.jumpTo({ center: [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2] });
  }

  /** Frame the units at the current instant, keeping the viewer's tilt: all of them, or just the main group. */
  fitAll(animate: boolean, camera: { pitch?: number; bearing?: number; duration?: number; group?: boolean } = {}): void {
    const s = this.controller.state.get();
    const states = statesAt(s.active.trajectory, this.controller.clock.timeS);
    const b = boundsOf(camera.group ? groupStates(states) : states);
    if (!b) return;
    this.map.fitBounds(b, {
      padding: camera.group ? 70 : { top: 100, bottom: 100, left: 100, right: 100 },
      maxZoom: camera.group ? 12.8 : 12.5,
      pitch: camera.pitch ?? this.map.getPitch(),
      bearing: camera.bearing ?? this.map.getBearing(),
      duration: camera.duration ?? (animate ? 1200 : 0),
    });
  }

  private onClick = (e: MapMouseEvent) => {
    const s = this.controller.state.get();
    if (s.placing && s.selectedId) {
      this.controller.addWaypoint(s.selectedId, { lon: e.lngLat.lng, lat: e.lngLat.lat });
      return;
    }
    this.controller.select(this.shipAt(e.point));
  };

  private onMouseMove = (e: MapMouseEvent) => {
    if (this.controller.state.get().placing) return;
    this.map.getCanvas().style.cursor = this.shipAt(e.point) ? 'pointer' : '';
  };

  private shipAt(point: MapMouseEvent['point']): string | null {
    const layers = PICK_LAYERS.filter((l) => this.map.getLayer(l));
    if (!layers.length) return null;
    const hit = this.map.queryRenderedFeatures(point, { layers })[0] as { properties?: Record<string, unknown> } | undefined;
    const id = hit?.properties?.id;
    return typeof id === 'string' ? id : null;
  }
}
