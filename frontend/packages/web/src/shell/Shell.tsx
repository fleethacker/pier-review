import { useCallback, useEffect, useRef, useState } from 'react';
import { getApp, listApps } from '../scene/app';
import type { AppInstance } from '../scene/app';
import type { SceneStore } from '../scene/store';
import type { SceneEdit } from '../scene/types';
import { CesiumCanvas } from './CesiumCanvas';
import { Inspector } from './Inspector';
import { ViewControls } from './ViewControls';

function initialAppId(): string {
  const fromUrl = new URLSearchParams(window.location.search).get('app');
  const apps = listApps();
  return apps.find((a) => a.id === fromUrl)?.id ?? apps[0]?.id ?? '';
}

export function Shell({ store }: { store: SceneStore }) {
  const [appId, setAppId] = useState(initialAppId);
  const [instance, setInstance] = useState<AppInstance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [upBearing, setUpBearing] = useState(0);
  const instanceRef = useRef<AppInstance | null>(null);

  useEffect(() => {
    const def = getApp(appId);
    if (!def) return;
    let cancelled = false;
    let started: AppInstance | null = null;
    setError(null);
    setInstance(null);
    store.clear();
    Promise.resolve(def.start({ store }))
      .then((inst) => {
        if (cancelled) return inst.dispose();
        started = inst;
        instanceRef.current = inst;
        setInstance(inst);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
      started?.dispose();
      instanceRef.current = null;
    };
  }, [appId, store]);

  const onEdit = useCallback((edit: SceneEdit) => instanceRef.current?.onEdit?.(edit), []);
  const apps = listApps();
  const { Sidebar, Bottom, Banner, Overlay } = instance ?? {};

  return (
    <div className="flex h-full w-full flex-col bg-mil-bg font-mono text-mil-text">
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-mil-border bg-mil-panel px-4">
        <div className="flex items-center gap-3">
          <span className="mil-label text-mil-amber">Mooring Assistant</span>
          {apps.length > 1 && (
            <select
              className="rounded-sm border border-mil-border bg-mil-bg px-2 py-1 text-xs text-white"
              value={appId}
              onChange={(e) => setAppId(e.target.value)}
              aria-label="Application"
            >
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}
                </option>
              ))}
            </select>
          )}
        </div>
        {Banner && <Banner />}
      </header>

      <div className="flex min-h-0 flex-1">
        {Sidebar && (
          <aside className="w-[360px] shrink-0 overflow-y-auto border-r border-mil-border bg-mil-panel/60 p-3">
            <Sidebar />
          </aside>
        )}
        <main className="relative min-w-0 flex-1">
          <CesiumCanvas store={store} onEdit={onEdit} onScreenUpBearing={setUpBearing} />
          <div className="pointer-events-none absolute inset-0">
            <ViewControls store={store} upBearingDeg={upBearing} />
            <div className="pointer-events-auto absolute right-3 top-20">
              <Inspector store={store} />
            </div>
            {error && (
              <div className="pointer-events-auto absolute left-1/2 top-16 -translate-x-1/2 rounded-sm border border-mil-red/60 bg-mil-panel px-4 py-2 text-xs text-mil-red">
                Could not start application: {error}
              </div>
            )}
          </div>
          {Overlay && (
            <div className="pointer-events-none absolute inset-0 z-20">
              <Overlay />
            </div>
          )}
        </main>
      </div>
      {Bottom && (
        <footer className="h-64 shrink-0 overflow-hidden border-t border-mil-border bg-mil-panel/60">
          <Bottom />
        </footer>
      )}
    </div>
  );
}
