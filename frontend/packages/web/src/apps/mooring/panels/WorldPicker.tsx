import { useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { cn } from '../../../lib/cn';
import { clusterPorts, groupPorts, mapBackground, mapPosition, portAt } from '../world';
import type { Port } from '../world';
import { useController, useMooring } from './context';

const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN as string | undefined;
// Whole world at zoom 0 is one 512 px square; the box below shows its middle band.
const MAP_IMAGE = TOKEN
  ? `url(https://api.mapbox.com/styles/v1/mapbox/dark-v11/static/0,0,0/512x512@2x?access_token=${TOKEN})`
  : undefined;
const BACKDROP = 'linear-gradient(180deg, #0d2a4a 0%, #0a1f3a 100%)';
const BG = mapBackground();

/**
 * Pick the berth by docking the ship at a port: drag the ship chip onto a port marker. A port with several berths
 * asks which one. Markers are also buttons, so a keyboard or a tap works without dragging. Only berths that already
 * exist can be chosen; nothing here creates one.
 */
export function WorldPicker() {
  const c = useController();
  const sites = useMooring((s) => s.berthSites);
  const berthId = useMooring((s) => s.berthId);
  const shipClassId = useMooring((s) => s.shipClassId);
  const ports = useMemo(() => clusterPorts(groupPorts(sites)), [sites]);
  const dots = useRef(new Map<string, HTMLElement>());
  const [drag, setDrag] = useState<{ x: number; y: number; over: string | null } | null>(null);
  const [choosing, setChoosing] = useState<string | null>(null);

  const current = ports.find((p) => p.berths.some((b) => b.berthId === berthId));
  const choosingPort = ports.find((p) => p.id === choosing) ?? null;
  const overPort = ports.find((p) => p.id === drag?.over) ?? null;

  const centres = () =>
    [...dots.current].map(([id, el]) => {
      const r = el.getBoundingClientRect();
      return { id, x: r.left + r.width / 2, y: r.top + r.height / 2 };
    });

  const dock = (port: Port) => {
    if (port.berths.length === 1) {
      setChoosing(null);
      if (port.berths[0].berthId !== berthId) void c.setBerth(port.berths[0].berthId);
    } else {
      setChoosing(port.id);
    }
  };

  const onDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ x: e.clientX, y: e.clientY, over: portAt(e.clientX, e.clientY, centres()) });
  };
  const onMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (drag) setDrag({ x: e.clientX, y: e.clientY, over: portAt(e.clientX, e.clientY, centres()) });
  };
  const onUp = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (!drag) return;
    const over = portAt(e.clientX, e.clientY, centres());
    setDrag(null);
    const port = ports.find((p) => p.id === over);
    if (port) dock(port);
  };

  return (
    <div className="space-y-2">
      <div
        className="relative w-full overflow-hidden rounded-sm border border-mil-border"
        style={{
          aspectRatio: BG.aspectRatio,
          backgroundImage: [MAP_IMAGE, BACKDROP].filter(Boolean).join(', '),
          backgroundSize: MAP_IMAGE ? `${BG.size}, 100% 100%` : '100% 100%',
          backgroundPosition: MAP_IMAGE ? `center ${BG.positionY}, center` : 'center',
        }}
        role="group"
        aria-label="World map of ports"
      >
        <div className="absolute inset-0 bg-mil-bg/10" />
        {ports.map((p) => {
          const pos = mapPosition(p.lat, p.lon);
          const here = p.id === current?.id;
          const over = p.id === drag?.over;
          return (
            <button
              key={p.id}
              type="button"
              ref={(el) => {
                if (el) dots.current.set(p.id, el);
                else dots.current.delete(p.id);
              }}
              onClick={() => dock(p)}
              title={`${p.label} (${p.berths.length} berth${p.berths.length > 1 ? 's' : ''})`}
              aria-label={`Port ${p.label}, ${p.berths.length} berth${p.berths.length > 1 ? 's' : ''}${here ? ', ship is here' : ''}`}
              className={cn(
                'absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition-transform focus:outline-none focus-visible:ring-2 focus-visible:ring-white',
                here ? 'border-mil-cyan bg-mil-cyan shadow-glow-cyan' : 'border-mil-amber bg-mil-bg hover:scale-125',
                over && 'scale-[1.8] border-white bg-mil-green',
              )}
              style={{ left: `${pos.x * 100}%`, top: `${pos.y * 100}%` }}
            />
          );
        })}
        {ports.length === 0 && <p className="absolute inset-0 flex items-center justify-center text-[11px] text-mil-dim">Loading ports…</p>}
      </div>

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={() => setDrag(null)}
          className={cn(
            'flex h-8 cursor-grab touch-none select-none items-center gap-2 rounded-sm border border-mil-cyan/60 bg-mil-cyan/15 px-3 font-mono text-[11px] uppercase text-mil-cyan active:cursor-grabbing',
            drag && 'opacity-50',
          )}
          aria-label="Ship. Drag it onto a port to dock there."
        >
          <span aria-hidden>▲</span> {shipClassId || 'Ship'}
        </button>
        <span className="min-w-0 flex-1 truncate text-right text-[11px] text-mil-text">
          {overPort ? `Drop to dock at ${overPort.label}` : current ? `Docked: ${current.label}` : 'Drag the ship onto a port'}
        </span>
      </div>

      {choosingPort && (
        <div className="space-y-1 rounded-sm border border-mil-border bg-mil-bg p-2" role="group" aria-label={`Berths at ${choosingPort.label}`}>
          <div className="flex items-center justify-between">
            <span className="mil-label">Berths at {choosingPort.label}</span>
            <button type="button" className="text-[11px] text-mil-dim hover:text-white" onClick={() => setChoosing(null)} aria-label="Cancel">
              ✕
            </button>
          </div>
          {choosingPort.berths.map((b) => (
            <button
              key={b.berthId}
              type="button"
              onClick={() => {
                setChoosing(null);
                if (b.berthId !== berthId) void c.setBerth(b.berthId);
              }}
              className={cn(
                'block w-full rounded-sm px-2 py-1 text-left text-[11px] hover:bg-mil-cyan/10',
                b.berthId === berthId ? 'text-mil-cyan' : 'text-white',
              )}
            >
              {b.name}
            </button>
          ))}
        </div>
      )}

      {drag && (
        <div
          className="pointer-events-none fixed z-50 whitespace-nowrap -translate-x-1/2 -translate-y-1/2 rounded-sm border border-mil-cyan bg-mil-panel px-2 py-1 font-mono text-[11px] uppercase text-mil-cyan shadow-glow-cyan"
          style={{ left: drag.x, top: drag.y }}
          aria-hidden
        >
          ▲ {shipClassId}
        </div>
      )}
      <p className="text-[10px] text-mil-dim">Drag the ship onto a port, or select a port, to dock at an existing berth.</p>
    </div>
  );
}
