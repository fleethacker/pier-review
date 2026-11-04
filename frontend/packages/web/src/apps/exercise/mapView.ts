import type { Map as MapboxMap, MapMouseEvent } from 'mapbox-gl';
import type { ExerciseController, ExerciseState } from './controller';
import { installAtmosphere, installLayers, PICK_LAYERS, setFrameData, setLabelsVisible, setStaticData } from './mapLayers';
import { styleById } from './mapStyles';
import { boundsOf, buildFrameData, buildStaticData } from './scene';
import { statesAt } from './sim';

type MapboxModule = typeof import('mapbox-gl').default;

export interface MapProblem {
  /** 'token' means nothing will load until the token changes; 'quota' means Mapbox is refusing some requests. */
  kind: 'token' | 'quota';
  message: string;
}

const START_PITCH = 62;
const START_BEARING = -25;

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
      zoom: 11.5,
      pitch: START_PITCH,
      bearing: START_BEARING,
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
    setLabelsVisible(this.map, state.view.showLabels);
    this.refreshStatic();
    this.draw();
    if (!this.framed) {
      this.framed = true;
      this.fitAll(false);
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
    if (now.active.scenario.lightPreset !== was.active.scenario.lightPreset && styleById(now.mapStyle).standard) {
      this.map.setConfigProperty('basemap', 'lightPreset', now.active.scenario.lightPreset);
    }
    if (now.view.showLabels !== was.view.showLabels) setLabelsVisible(this.map, now.view.showLabels);
    if (
      now.active !== was.active ||
      now.selectedId !== was.selectedId ||
      now.view.showRoutes !== was.view.showRoutes
    ) {
      this.refreshStatic();
    }
    if (now.scenarioRevision !== was.scenarioRevision || now.fitRevision !== was.fitRevision) this.fitAll(true);
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
    if (s.follow !== 'off' && s.selectedId) {
      const i = s.active.trajectory.unitIds.indexOf(s.selectedId);
      if (i >= 0) {
        const st = statesAt(s.active.trajectory, t)[i];
        this.map.jumpTo(s.follow === 'chase' ? { center: [st.lon, st.lat], bearing: st.headingDeg } : { center: [st.lon, st.lat] });
      }
    }
  };

  /** Frame every unit at the current instant, keeping the viewer's tilt. */
  fitAll(animate: boolean): void {
    const s = this.controller.state.get();
    const b = boundsOf(statesAt(s.active.trajectory, this.controller.clock.timeS));
    if (!b) return;
    this.map.fitBounds(b, {
      padding: { top: 90, bottom: 90, left: 90, right: 90 },
      maxZoom: 12.5,
      pitch: this.map.getPitch(),
      bearing: this.map.getBearing(),
      duration: animate ? 1200 : 0,
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
