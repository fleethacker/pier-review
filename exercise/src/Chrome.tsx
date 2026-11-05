import { useCallback, useEffect, useRef, useState } from 'react';
import { cn } from './lib/cn';
import type { AppDefinition, AppInstance, AppTab } from './lib/app';

export const PRODUCT_NAME = 'Exercise simulator';

export function tabsOf(def: AppDefinition): AppTab[] {
  return def.tabs?.length ? def.tabs : [{ id: 'main', label: def.title }];
}

/** Which view is open, from the address bar, so a link can point at one. */
export function tabFromUrl(search: string, def: AppDefinition): string {
  const wanted = new URLSearchParams(search).get('tab');
  const tabs = tabsOf(def);
  return tabs.find((t) => t.id === wanted)?.id ?? tabs[0].id;
}

/**
 * The page frame: a tab bar and the application's panels around its map. One application, started once, so there is no
 * landing page and nothing to choose.
 */
export function Chrome({ def }: { def: AppDefinition }) {
  const [tabId, setTabId] = useState(() => tabFromUrl(window.location.search, def));
  const [instance, setInstance] = useState<AppInstance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let live: AppInstance | null = null;
    let dropped = false;
    Promise.resolve(def.start({}))
      .then((inst) => {
        if (dropped) return inst.dispose();
        live = inst;
        setInstance(inst);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    return () => {
      dropped = true;
      live?.dispose();
    };
  }, [def]);

  const go = useCallback((id: string) => {
    setTabId(id);
    const url = new URL(window.location.href);
    url.searchParams.set('tab', id);
    window.history.pushState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }, []);

  useEffect(() => {
    const onPop = () => setTabId(tabFromUrl(window.location.search, def));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [def]);

  useEffect(() => {
    instance?.setTab?.(tabId);
  }, [instance, tabId]);

  const tabs = tabsOf(def);
  const { Sidebar, Side, Bottom, Banner, Overlay, Canvas } = instance ?? {};

  return (
    <div className="flex h-full w-full flex-col bg-mil-bg font-mono text-mil-text">
      <header className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-mil-border bg-mil-panel px-4 py-1">
        <span className="mil-label text-mil-amber">{PRODUCT_NAME}</span>
        <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1">
          {tabs.length > 1 && <TabBar tabs={tabs} active={tabId} label={`${def.title} views`} onSelect={go} />}
          {Banner && <Banner />}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {Sidebar && (
          <aside
            className="w-[300px] shrink-0 overflow-y-auto border-r border-mil-border bg-mil-panel/60 p-3 md:w-[360px]"
            role="tabpanel"
            id="exercise-tabpanel"
            aria-labelledby={`exercise-tab-${tabId}`}
          >
            <Sidebar />
          </aside>
        )}
        <main className="relative min-w-0 flex-1">
          {Canvas && <Canvas />}
          {error && (
            <div className="pointer-events-auto absolute left-1/2 top-16 z-30 -translate-x-1/2 rounded-sm border border-mil-red/60 bg-mil-panel px-4 py-2 text-xs text-mil-red">
              Could not start the simulator: {error}
            </div>
          )}
          {Overlay && (
            <div className="pointer-events-none absolute inset-0 z-20">
              <Overlay />
            </div>
          )}
        </main>
        {Side && (
          <aside className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-mil-border bg-mil-panel/60 p-3 lg:block">
            <Side />
          </aside>
        )}
      </div>
      {Bottom && (
        <footer className="h-64 shrink-0 overflow-hidden border-t border-mil-border bg-mil-panel/60">
          <Bottom />
        </footer>
      )}
    </div>
  );
}

function TabBar({ tabs, active, label, onSelect }: { tabs: AppTab[]; active: string; label: string; onSelect: (id: string) => void }) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  const move = (delta: number) => {
    const i = tabs.findIndex((t) => t.id === active);
    const next = tabs[(i + delta + tabs.length) % tabs.length];
    onSelect(next.id);
    refs.current.get(next.id)?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          ref={(el) => {
            if (el) refs.current.set(t.id, el);
          }}
          role="tab"
          id={`exercise-tab-${t.id}`}
          aria-selected={t.id === active}
          aria-controls="exercise-tabpanel"
          tabIndex={t.id === active ? 0 : -1}
          onClick={() => onSelect(t.id)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight') move(1);
            else if (e.key === 'ArrowLeft') move(-1);
            else if (e.key === 'Home') onSelect(tabs[0].id);
            else if (e.key === 'End') onSelect(tabs[tabs.length - 1].id);
          }}
          className={cn(
            'rounded-sm border px-3 py-1 text-[11px] uppercase tracking-wider',
            t.id === active
              ? 'border-mil-cyan/60 bg-mil-cyan/15 text-mil-cyan'
              : 'border-mil-border text-mil-dim hover:border-mil-cyan/40 hover:text-white',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
