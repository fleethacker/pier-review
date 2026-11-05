import { useCallback, useEffect, useRef, useState } from 'react';
import { cn } from '../../lib/cn';
import { Button, inputClass } from '../../shell/ui';
import { useClockSecond, useController, useExercise } from './context';
import { PLAYBACK_RATES } from './controller';
import { formatClock } from './geo';
import { reportClientError } from './clientErrors';
import { downloadBlob } from './exportResults';
import { slugify } from './library';
import { getMapboxToken, saveMapboxToken } from './mapStyles';
import { canRecord, startRecording } from './recorder';
import type { Recording } from './recorder';
import { fetchConfig } from './serverApi';
import type { ExerciseMapView, MapProblem } from './mapView';

function TokenPrompt({ onSave, message }: { onSave: (token: string) => void; message?: string | null }) {
  const [value, setValue] = useState('');
  const valid = /^pk\.[\w-]+\.[\w-]+$/.test(value.trim());
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-mil-bg">
      <form
        className="glass-panel mil-brackets w-[420px] space-y-3 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) onSave(value.trim());
        }}
      >
        <h3 className="mil-label text-[11px]">Mapbox access token</h3>
        {message && <p className="text-xs text-mil-red">{message}</p>}
        <p className="text-xs text-mil-text">
          The exercise map is drawn by Mapbox, which needs a public access token (starts with <code>pk.</code>). Create one
          at account.mapbox.com. It stays in this browser. To set it for everyone, give the app a <code>MAPBOX_TOKEN</code>{' '}
          environment variable and restart it (or build with <code>VITE_MAPBOX_TOKEN</code>).
        </p>
        <input
          className={inputClass}
          placeholder="pk.eyJ1…"
          aria-label="Mapbox access token"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <Button type="submit" size="sm" disabled={!valid}>
          Use this token
        </Button>
      </form>
    </div>
  );
}

function ToolButton({ pressed, onClick, children, title }: { pressed?: boolean; onClick: () => void; children: string; title: string }) {
  return (
    <button
      title={title}
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        'border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider backdrop-blur',
        pressed ? 'border-mil-cyan/70 bg-mil-cyan/25 text-mil-cyan' : 'border-mil-border bg-mil-panel/85 text-mil-text hover:text-white',
      )}
    >
      {children}
    </button>
  );
}

function Toolbar({ recording, onRecord }: { recording: boolean; onRecord: () => void }) {
  const c = useController();
  const follow = useExercise((s) => s.follow);
  const placing = useExercise((s) => s.placing);
  const redTeamOpen = useExercise((s) => s.redTeamOpen);
  const replay = useExercise((s) => s.replay);
  const selectedId = useExercise((s) => s.selectedId);
  const runOverlay = useExercise((s) => s.runOverlay);
  const name = useExercise((s) => s.scenario.units.find((u) => u.id === s.selectedId)?.name ?? null);

  useEffect(() => {
    if (!placing) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && c.setPlacing(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [placing, c]);

  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex flex-col items-center gap-2 p-3">
      <div className="pointer-events-auto flex gap-1.5 self-start" role="toolbar" aria-label="Camera">
        <ToolButton title="Frame every ship" onClick={() => c.fitAll()}>
          Fit all
        </ToolButton>
        <ToolButton title="Keep the selected ship centered" pressed={follow === 'follow'} onClick={() => c.setFollow(follow === 'follow' ? 'off' : 'follow')}>
          Follow
        </ToolButton>
        <ToolButton title="Follow the selected ship and look the way it points" pressed={follow === 'chase'} onClick={() => c.setFollow(follow === 'chase' ? 'off' : 'chase')}>
          Chase
        </ToolButton>
        <ToolButton title="Circle the selected ship, or the whole group" pressed={follow === 'orbit'} onClick={() => c.setFollow(follow === 'orbit' ? 'off' : 'orbit')}>
          Orbit
        </ToolButton>
        <ToolButton title="Hide the panels and fill the screen with the map" onClick={() => c.setPresenting(true)}>
          Present
        </ToolButton>
        <ToolButton title="Run the scenario many times with random variation and measure how often things happen" pressed={redTeamOpen} onClick={() => c.toggleRedTeam()}>
          Red team
        </ToolButton>
        <ToolButton title="Click the map to add waypoints to the selected ship" pressed={placing} onClick={() => c.setPlacing(!placing)}>
          Add waypoints
        </ToolButton>
        <ToolButton title={recording ? 'Stop recording and save the video' : 'Play the scenario from here and record the map as a video'} pressed={recording} onClick={onRecord}>
          {recording ? '● Stop' : 'Record'}
        </ToolButton>
      </div>
      {runOverlay && (
        <div role="status" className="pointer-events-auto max-w-[44rem] space-y-1 border border-mil-border bg-mil-panel/95 px-3 py-2 text-xs text-mil-text">
          <p>
            {runOverlay.working ? 'Working out the paths…' : `Paths from ${runOverlay.hitRuns + runOverlay.missRuns} runs for “${runOverlay.label}”:`}{' '}
            <span className="text-[#ff5a4a]">red where it happened ({runOverlay.hitRuns})</span>, <span className="text-[#4adf9a]">green where it did not ({runOverlay.missRuns})</span>. Thick lines are ships and aircraft, thin ones missiles and torpedoes.
          </p>
          <div className="flex gap-3 text-[10px] uppercase tracking-wider">
            <button className="text-mil-cyan hover:text-white" onClick={() => c.toggleRedTeam(true)}>
              Back to red team
            </button>
            <button className="text-mil-cyan hover:text-white" onClick={() => c.clearRunOverlay()}>
              Clear paths
            </button>
          </div>
        </div>
      )}
      {replay && (
        <div role="status" className="pointer-events-auto max-w-[44rem] space-y-1 border border-mil-amber/60 bg-mil-panel/95 px-3 py-2 text-xs text-mil-amber">
          <p>
            Replaying run {replay.run} of a red-team batch ({replay.groupLabel}
            {replay.outcomeLabel ? `, chosen for: ${replay.outcomeLabel}` : ''}). Press Play to watch it.
          </p>
          <details className="text-[10px] text-mil-text">
            <summary className="cursor-pointer">The random draws in this run</summary>
            <ul className="mt-1 grid grid-cols-2 gap-x-4">
              {replay.values.map((v) => (
                <li key={v.label} className="flex justify-between gap-2">
                  <span className="truncate">{v.label}</span>
                  <span className="tabular-nums text-white">{Number(v.value.toFixed(3))}</span>
                </li>
              ))}
            </ul>
          </details>
          <div className="flex gap-3 text-[10px] uppercase tracking-wider">
            <button className="text-mil-cyan hover:text-white" onClick={() => c.toggleRedTeam(true)}>
              Back to red team
            </button>
            <button className="text-mil-cyan hover:text-white" onClick={() => c.exitReplay()}>
              Exit replay
            </button>
          </div>
        </div>
      )}
      {placing && selectedId && (
        <div role="status" className="pointer-events-auto border border-mil-cyan/50 bg-mil-panel/90 px-3 py-1.5 text-xs text-mil-cyan">
          Click the map to add waypoints to {name}. Press Esc or the button to stop.
        </div>
      )}
    </div>
  );
}

/** The little that stays on screen in presentation mode: what this is, the time, and the playback controls. */
function PresentHud() {
  const c = useController();
  const second = useClockSecond();
  const name = useExercise((s) => s.active.scenario.name);
  const playing = useExercise((s) => s.playing);
  const rate = useExercise((s) => s.rate);
  const duration = useExercise((s) => s.active.scenario.durationS);
  return (
    <>
      <div className="pointer-events-none absolute right-5 top-4 z-10 text-right drop-shadow-[0_1px_6px_rgba(0,0,0,0.8)]">
        <div className="font-mono text-[11px] uppercase tracking-[0.25em] text-mil-cyan">{name}</div>
        <div className="mt-1 font-mono text-3xl font-light tabular-nums text-white">T+{formatClock(second)}</div>
      </div>
      <div className="absolute inset-x-0 bottom-5 z-10 flex justify-center">
        <div className="flex items-center gap-3 rounded-sm border border-mil-border bg-mil-panel/80 px-4 py-2 backdrop-blur" role="group" aria-label="Presentation controls">
          <button aria-label={playing ? 'Pause' : 'Play'} onClick={() => c.togglePlay()} className="w-14 font-mono text-[11px] uppercase tracking-wider text-mil-cyan hover:text-white">
            {playing ? 'Pause' : 'Play'}
          </button>
          <input type="range" aria-label="Time" className="w-72" min={0} max={duration} step={1} value={second} onChange={(e) => c.seek(Number(e.target.value))} />
          <select aria-label="Playback speed" className="rounded-sm border border-mil-border bg-mil-bg px-1.5 py-1 font-mono text-xs text-white" value={rate} onChange={(e) => c.setRate(Number(e.target.value))}>
            {PLAYBACK_RATES.map((r) => (
              <option key={r} value={r}>
                {r}×
              </option>
            ))}
          </select>
          <button onClick={() => c.setPresenting(false)} className="font-mono text-[11px] uppercase tracking-wider text-mil-text hover:text-white">
            Exit
          </button>
        </div>
      </div>
    </>
  );
}

export function MapCanvas() {
  const c = useController();
  const host = useRef<HTMLDivElement>(null);
  const [token, setToken] = useState(getMapboxToken);
  const [problem, setProblem] = useState<MapProblem | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const askedServer = useRef(false);
  const viewRef = useRef<ExerciseMapView | null>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const presenting = useExercise((s) => s.presenting);

  useEffect(() => {
    if (!presenting) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !c.state.get().placing && c.setPresenting(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [presenting, c]);

  // No token in the build or this browser: the server may have one (MAPBOX_TOKEN in the app's environment). Ask once.
  useEffect(() => {
    if (token || askedServer.current || problem?.kind === 'token') return;
    askedServer.current = true;
    let cancelled = false;
    fetchConfig().then(
      (cfg) => !cancelled && cfg.mapboxToken && setToken(cfg.mapboxToken),
      () => undefined, // No server to ask: the prompt below is the way forward.
    );
    return () => {
      cancelled = true;
    };
  }, [token, problem]);

  useEffect(() => {
    if (!token || !host.current) return;
    const container = host.current;
    let view: ExerciseMapView | null = null;
    let cancelled = false;
    setLoading(true);
    // Mapbox GL is large; load it only when this tab opens.
    Promise.all([import('mapbox-gl'), import('./mapView'), import('mapbox-gl/dist/mapbox-gl.css')])
      .then(([mapbox, { ExerciseMapView: View }]) => {
        if (cancelled) return;
        view = new View(container, mapbox.default, token, c, (p) => {
          setProblem(p);
          reportClientError(p.kind, p.message);
          if (p.kind === 'token') setToken('');
        });
        viewRef.current = view;
        setLoading(false);
        if (import.meta.env.DEV) (window as unknown as { __exerciseMap: unknown }).__exerciseMap = view.map;
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const text = e instanceof Error ? e.message : String(e);
        setLoadError(text);
        reportClientError('load', text, e instanceof Error ? e.stack : undefined);
      });
    return () => {
      cancelled = true;
      viewRef.current = null;
      view?.dispose();
    };
  }, [token, c]);

  const finishRecording = useCallback(
    async (rec: Recording) => {
      setRecording(null);
      try {
        const blob = await rec.stop();
        const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..*$/, '').replace('T', '-');
        downloadBlob(`${slugify(c.state.get().scenario.name)}-${stamp}.webm`, blob);
      } catch (e) {
        setRecordError(e instanceof Error ? e.message : String(e));
      }
    },
    [c],
  );

  const toggleRecord = () => {
    if (recording) {
      void finishRecording(recording);
      return;
    }
    setRecordError(null);
    const canvas = viewRef.current?.map.getCanvas();
    if (!canvas || !canRecord(canvas)) {
      setRecordError('This browser cannot record the map. Try a recent Chrome, Edge or Firefox.');
      return;
    }
    try {
      setRecording(startRecording(canvas));
      c.play();
    } catch (e) {
      setRecordError(e instanceof Error ? e.message : String(e));
    }
  };

  // The recording ends by itself when the run does, a moment later so the last frames are in it.
  useEffect(() => {
    if (!recording) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = c.clock.subscribe(() => {
      if (!timer && c.clock.timeS >= c.clock.durationS) timer = setTimeout(() => void finishRecording(recording), 800);
    });
    return () => {
      off();
      clearTimeout(timer);
    };
  }, [recording, c, finishRecording]);
  // Leaving the tab ends it too, and keeps what was recorded.
  useEffect(() => () => void recording?.stop().catch(() => undefined), [recording]);

  if (!token) {
    return (
      <TokenPrompt
        message={problem?.kind === 'token' ? problem.message : null}
        onSave={(t) => {
          saveMapboxToken(t);
          setProblem(null);
          setToken(t);
        }}
      />
    );
  }
  return (
    <div className={cn('bg-mil-bg', presenting ? 'fixed inset-0 z-50' : 'absolute inset-0')}>
      {/* Inline size: Mapbox's stylesheet sets position: relative on its container and would otherwise win over a class. */}
      <div ref={host} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} data-testid="exercise-map" />
      {loading && !loadError && <p className="absolute left-1/2 top-1/2 -translate-x-1/2 text-xs text-mil-cyan">Loading map…</p>}
      {recording && <p className="absolute right-4 top-14 z-20 font-mono text-[11px] uppercase tracking-wider text-mil-red">● Recording</p>}
      {(loadError || problem || recordError) && (
        <p role="alert" className="absolute left-1/2 top-16 z-20 max-w-[34rem] -translate-x-1/2 border border-mil-amber/60 bg-mil-panel px-4 py-2 text-xs text-mil-amber">
          {loadError ?? problem?.message ?? recordError}
        </p>
      )}
      <Toolbar recording={!!recording} onRecord={toggleRecord} />
      {presenting && <PresentHud />}
    </div>
  );
}
