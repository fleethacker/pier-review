import type { Map as MapboxMap, MapMouseEvent } from 'mapbox-gl';
import type { ExerciseController, ExerciseState } from './controller';
import { HANDLE_LAYER, installAtmosphere, installLayers, PICK_LAYERS, setDragGhost, setFrameData, setLabelsVisible, setLightLevel, setRunTracks, setStaticData, WAYPOINT_LAYER } from './mapLayers';
import { styleById } from './mapStyles';
import { boundsOf, buildFrameData, buildStaticData, groupStates } from './scene';
import type { FollowMode } from './controller';
import { statesAt } from './sim';
import { SIDE_COLORS } from './ships';
import { createBubble, momentAnchor, momentsAt } from './storyboard';

type MapboxModule = typeof import('mapbox-gl').default;
type Marker = import('mapbox-gl').Marker;

export interface MapProblem {
  /** 'token' means nothing will load until the token changes; 'quota' means Mapbox is refusing some requests; 'webgl' means the browser took the graphics context away. */
  kind: 'token' | 'quota' | 'webgl';
  message: string;
}

const START_PITCH = 62;
const START_BEARING = -25;
const INTRO_MS = 3800;
const ORBIT_DEG_PER_S = 5;
/** How far the pointer has to travel, in pixels, before a press on a ship or handle becomes a drag rather than a click. */
const DRAG_THRESHOLD_PX = 4;

type DragKind = 'unit' | 'waypoint' | 'insert';
interface Drag {
  kind: DragKind;
  id: string;
  /** Waypoint number (from 0), or where the new waypoint goes. */
  index: number;
  from: [number, number];
  startPx: { x: number; y: number };
  moved: boolean;
}

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

  private readonly mapbox: MapboxModule;
  /** The bubble on the map for each storyboard beat that is up, by beat id. */
  private bubbles = new Map<string, { marker: Marker; el: HTMLElement }>();

  constructor(
    container: HTMLElement,
    mapbox: MapboxModule,
    token: string,
    private readonly controller: ExerciseController,
    private readonly onProblem: (problem: MapProblem) => void,
  ) {
    const state = controller.state.get();
    this.prev = state;
    this.mapbox = mapbox;
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
    this.map.on('mousedown', this.onMouseDown);
    this.map.on('mouseup', this.onMouseUp);
    this.map.on('contextmenu', this.onContextMenu);
    this.map.on('error', this.onError);
    if (typeof window !== 'undefined') {
      window.addEventListener('mouseup', this.onWindowUp);
      window.addEventListener('keydown', this.onKey);
    }
    this.map.getCanvas().addEventListener('webglcontextlost', this.onContextLost);
    if (typeof ResizeObserver !== 'undefined') {
      this.resizer = new ResizeObserver(() => this.map.resize());
      this.resizer.observe(container);
    }
    this.offStore = controller.state.subscribe(this.onStore);
    this.offClock = controller.clock.subscribe(this.draw);
    controller.setCapture(this.capture);
  }

  dispose(): void {
    this.controller.setCapture(null);
    this.clearBubbles();
    this.offStore();
    this.offClock();
    cancelAnimationFrame(this.orbiting);
    this.resizer?.disconnect();
    this.map.getCanvas()?.removeEventListener('webglcontextlost', this.onContextLost);
    if (typeof window !== 'undefined') {
      window.removeEventListener('mouseup', this.onWindowUp);
      window.removeEventListener('keydown', this.onKey);
    }
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
    setRunTracks(this.map, state.runOverlay?.tracks ?? []);
    this.draw();
    if (!this.framed) {
      this.framed = true;
      // Open high and tilted down, then glide in to the main group so the ships are big enough to see in 3D.
      this.fitAll(true, { pitch: START_PITCH, bearing: START_BEARING, duration: INTRO_MS, group: true });
    }
  };

  private onContextLost = (e: Event) => {
    // Let the browser restore it if it can; say so in the meantime.
    e.preventDefault();
    this.onProblem({ kind: 'webgl', message: 'The browser took the graphics context away from the map (often because of memory or a GPU reset). It may come back by itself; if not, reload the page.' });
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
    if (now.runOverlay !== was.runOverlay) setRunTracks(this.map, now.runOverlay?.tracks ?? []);
    // A beat whose picture or words changed has to be built again, so drop its bubble and let the next frame remake it.
    if (now.active.scenario.storyboard !== was.active.scenario.storyboard || now.view.showStory !== was.view.showStory) this.clearBubbles();
    if (now.scenarioRevision !== was.scenarioRevision) this.fitAll(true, { group: true });
    else if (now.fitRevision !== was.fitRevision) this.fitAll(true);
    if (now.follow !== was.follow) this.setOrbiting(now.follow);
    if (!this.drag) this.map.getCanvas().style.cursor = now.placing ? 'crosshair' : '';
    // State the map does not show (a Monte Carlo batch reporting progress, say) must not make it rebuild every ship.
    const changed =
      now.active !== was.active ||
      now.selectedId !== was.selectedId ||
      now.view !== was.view ||
      now.follow !== was.follow ||
      now.active.scenario.storyboard !== was.active.scenario.storyboard ||
      now.scenarioRevision !== was.scenarioRevision ||
      now.fitRevision !== was.fitRevision;
    if (changed) this.draw();
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
    this.syncBubbles(t);
    this.keepCentered(s.follow, s.selectedId, t);
  };

  /**
   * A picture of the map as it looks now, as a JPEG data URI. The drawing buffer is cleared after every frame, so the pixels
   * are read inside a render rather than after one, and scaled down on the way out to keep the scenario file small.
   */
  capture = (maxWidth = 520, quality = 0.72): Promise<string> =>
    new Promise<string>((resolve, reject) => {
      const source = this.map.getCanvas();
      this.map.once('render', () => {
        try {
          const scale = Math.min(1, maxWidth / source.width);
          const out = document.createElement('canvas');
          out.width = Math.max(1, Math.round(source.width * scale));
          out.height = Math.max(1, Math.round(source.height * scale));
          const ctx = out.getContext('2d');
          if (!ctx) throw new Error('This browser would not give a drawing context to copy the map into.');
          ctx.drawImage(source, 0, 0, out.width, out.height);
          resolve(out.toDataURL('image/jpeg', quality));
        } catch (e) {
          reject(e instanceof Error ? e : new Error(String(e)));
        }
      });
      this.map.triggerRepaint();
    });

  private clearBubbles(): void {
    for (const b of this.bubbles.values()) b.marker.remove();
    this.bubbles.clear();
  }

  /**
   * Put a bubble beside each unit that has a storyboard beat up at `timeS`, move the ones already there, and take away the
   * ones whose time is past. Markers are kept between frames so scrubbing does not rebuild the DOM on every tick.
   */
  private syncBubbles(timeS: number): void {
    const s = this.controller.state.get();
    const { scenario, trajectory } = s.active;
    const moments = s.view.showStory ? (scenario.storyboard ?? []) : [];
    const live = moments.length ? momentsAt(moments, timeS) : [];
    const wanted = new Set<string>();

    for (const { moment, opacity } of live) {
      const at = momentAnchor(scenario, trajectory, moment, timeS);
      if (!at) continue;
      wanted.add(moment.id);
      let held = this.bubbles.get(moment.id);
      if (!held) {
        const unit = moment.unitId ? scenario.units.find((u) => u.id === moment.unitId) : undefined;
        const el = createBubble(moment, {
          color: unit ? SIDE_COLORS[unit.side] : '#7ad7ff',
          onClick: () => this.controller.focusMoment(moment.id),
        });
        const marker = new this.mapbox.Marker({ element: el, anchor: 'bottom', offset: [0, -14] }).setLngLat([at.lon, at.lat]).addTo(this.map);
        held = { marker, el };
        this.bubbles.set(moment.id, held);
      }
      held.marker.setLngLat([at.lon, at.lat]);
      held.el.style.opacity = String(opacity);
    }

    for (const [id, b] of this.bubbles) {
      if (wanted.has(id)) continue;
      b.marker.remove();
      this.bubbles.delete(id);
    }
  }

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

  private suppressClick = false;

  private onClick = (e: MapMouseEvent) => {
    if (this.suppressClick) {
      // The click that ends a drag is not a selection.
      this.suppressClick = false;
      return;
    }
    const s = this.controller.state.get();
    if (s.placing && s.selectedId) {
      this.controller.addWaypoint(s.selectedId, { lon: e.lngLat.lng, lat: e.lngLat.lat });
      return;
    }
    this.controller.select(this.shipAt(e.point));
  };

  /** Dragging edits the scenario, so it is off while placing waypoints, while a replayed run is on screen, and for ships once the clock has moved. */
  private canEdit(): boolean {
    const s = this.controller.state.get();
    return this.styleReady && !s.placing && !s.replay;
  }

  private drag: Drag | null = null;

  private onMouseDown = (e: MapMouseEvent) => {
    if (!this.canEdit() || (e.originalEvent as MouseEvent | undefined)?.button) return;
    const s = this.controller.state.get();
    let drag: Omit<Drag, 'startPx' | 'moved'> | null = null;
    const wp = this.featureAt(e.point, WAYPOINT_LAYER);
    const mid = wp ? null : this.featureAt(e.point, HANDLE_LAYER);
    if (wp && wp.selected === true && typeof wp.id === 'string' && typeof wp.n === 'number') {
      const u = s.scenario.units.find((x) => x.id === wp.id);
      const p = u?.behavior.type === 'route' ? u.behavior.waypoints[wp.n] : undefined;
      if (p) drag = { kind: 'waypoint', id: wp.id, index: wp.n, from: [p.lon, p.lat] };
    } else if (mid && typeof mid.id === 'string' && typeof mid.insertAt === 'number') {
      drag = { kind: 'insert', id: mid.id, index: mid.insertAt, from: [e.lngLat.lng, e.lngLat.lat] };
    } else if (this.controller.clock.timeS === 0) {
      const id = this.shipAt(e.point);
      const u = id ? s.scenario.units.find((x) => x.id === id) : undefined;
      if (u && !u.launch) drag = { kind: 'unit', id: u.id, index: 0, from: [u.start.lon, u.start.lat] };
    }
    if (!drag) return;
    this.drag = { ...drag, startPx: { x: e.point.x, y: e.point.y }, moved: false };
    // Without this the map would pan along with the drag.
    e.preventDefault();
  };

  private onMouseUp = (e: MapMouseEvent) => this.endDrag([e.lngLat.lng, e.lngLat.lat]);
  /** A release outside the map still ends the drag, without moving anything. */
  private onWindowUp = () => this.endDrag(null);

  private onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape' && this.drag) {
      this.drag = null;
      setDragGhost(this.map, null);
      this.map.getCanvas().style.cursor = '';
    }
  };

  private endDrag(at: [number, number] | null): void {
    const d = this.drag;
    if (!d) return;
    this.drag = null;
    setDragGhost(this.map, null);
    this.map.getCanvas().style.cursor = '';
    if (!d.moved || !at) return;
    this.suppressClick = true;
    const to = { lon: at[0], lat: at[1] };
    if (d.kind === 'unit') {
      this.controller.patchUnit(d.id, { start: to });
      this.controller.select(d.id);
    } else if (d.kind === 'waypoint') this.controller.patchWaypoint(d.id, d.index, to);
    else this.controller.insertWaypoint(d.id, d.index, to);
  }

  /** Right-click a waypoint of the selected route to remove it. */
  private onContextMenu = (e: MapMouseEvent) => {
    if (!this.canEdit()) return;
    const wp = this.featureAt(e.point, WAYPOINT_LAYER);
    if (!wp || wp.selected !== true || typeof wp.id !== 'string' || typeof wp.n !== 'number') return;
    e.preventDefault();
    const u = this.controller.state.get().scenario.units.find((x) => x.id === wp.id);
    if (u?.behavior.type === 'route' && u.behavior.waypoints.length > 1) this.controller.removeWaypoint(wp.id, wp.n);
    else this.controller.notify('A route needs at least one waypoint.');
  };

  private onMouseMove = (e: MapMouseEvent) => {
    const d = this.drag;
    if (d) {
      if (!d.moved && Math.hypot(e.point.x - d.startPx.x, e.point.y - d.startPx.y) < DRAG_THRESHOLD_PX) return;
      d.moved = true;
      this.map.getCanvas().style.cursor = 'grabbing';
      setDragGhost(this.map, { from: d.from, to: [e.lngLat.lng, e.lngLat.lat] });
      return;
    }
    if (this.controller.state.get().placing) return;
    const canEdit = this.canEdit();
    const wp = canEdit ? this.featureAt(e.point, WAYPOINT_LAYER) : null;
    if (wp?.selected === true) this.map.getCanvas().style.cursor = 'grab';
    else if (canEdit && this.featureAt(e.point, HANDLE_LAYER)) this.map.getCanvas().style.cursor = 'copy';
    else {
      const id = this.shipAt(e.point);
      const draggable = canEdit && this.controller.clock.timeS === 0 && !!this.controller.state.get().scenario.units.find((u) => u.id === id && !u.launch);
      this.map.getCanvas().style.cursor = id ? (draggable ? 'grab' : 'pointer') : '';
    }
  };

  private featureAt(point: MapMouseEvent['point'], layer: string): Record<string, unknown> | null {
    if (!this.map.getLayer(layer)) return null;
    const hit = this.map.queryRenderedFeatures(point, { layers: [layer] })[0] as { properties?: Record<string, unknown> } | undefined;
    return hit?.properties ?? null;
  }

  private shipAt(point: MapMouseEvent['point']): string | null {
    const layers = PICK_LAYERS.filter((l) => this.map.getLayer(l));
    if (!layers.length) return null;
    const hit = this.map.queryRenderedFeatures(point, { layers })[0] as { properties?: Record<string, unknown> } | undefined;
    const id = hit?.properties?.id;
    return typeof id === 'string' ? id : null;
  }
}
