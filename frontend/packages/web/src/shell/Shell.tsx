import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '../lib/cn';
import { getApp, listApps } from '../scene/app';
import type { AppDefinition, AppInstance, AppTab } from '../scene/app';
import { SceneStore } from '../scene/store';
import type { SceneEdit } from '../scene/types';
import { CesiumCanvas } from './CesiumCanvas';
import { Inspector } from './Inspector';
import { Landing } from './Landing';
import { ViewControls } from './ViewControls';

export const PRODUCT_NAME = 'Pier Review';

/** Where the shell is: the landing page, or one tab of one application. */
export type Route = { appId: null } | { appId: string; tabId: string };

export function tabsOf(def: AppDefinition): AppTab[] {
  return def.tabs?.length ? def.tabs : [{ id: 'main', label: def.title }];
}

/** Route from the address bar. With a single application there is nothing to choose, so it opens directly. */
export function routeFromUrl(search: string, apps: AppDefinition[]): Route {
  const params = new URLSearchParams(search);
  const def = apps.find((a) => a.id === params.get('app')) ?? (apps.length === 1 ? apps[0] : undefined);
  if (!def) return { appId: null };
  const tabs = tabsOf(def);
  return { appId: def.id, tabId: tabs.find((t) => t.id === params.get('tab'))?.id ?? tabs[0].id };
}

function urlFor(route: Route): string {
  const url = new URL(window.location.href);
  url.searchParams.delete('app');
  url.searchParams.delete('tab');
  if (route.appId) {
    url.searchParams.set('app', route.appId);
    url.searchParams.set('tab', route.tabId);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

interface Running {
  store: SceneStore;
  instance: AppInstance | null;
  error: string | null;
}

/**
 * The page frame: a landing page listing every application built on the physics services, and for the open
 * application a tab bar, its panels and the shared 3D canvas. Applications start on first visit and keep running when
 * you switch away, each with its own scene, so returning finds the work as it was.
 */
export function Shell({ store }: { store?: SceneStore }) {
  const apps = listApps();
  const [route, setRoute] = useState<Route>(() => routeFromUrl(window.location.search, apps));
  const [, setVersion] = useState(0);
  const [upBearing, setUpBearing] = useState(0);
  const running = useRef(new Map<string, Running>());
  const fallbackStore = useMemo(() => store ?? null, [store]);

  // Start an application the first time it is opened; keep it afterwards.
  const ensure = useCallback(
    (appId: string): Running | null => {
      const existing = running.current.get(appId);
      if (existing) return existing;
      const def = getApp(appId);
      if (!def) return null;
      const appStore = running.current.size === 0 && fallbackStore ? fallbackStore : new SceneStore();
      const entry: Running = { store: appStore, instance: null, error: null };
      running.current.set(appId, entry);
      Promise.resolve(def.start({ store: entry.store }))
        .then((inst) => {
          if (running.current.get(appId) !== entry) return inst.dispose();
          entry.instance = inst;
          setVersion((v) => v + 1);
        })
        .catch((e: unknown) => {
          entry.error = e instanceof Error ? e.message : String(e);
          setVersion((v) => v + 1);
        });
      return entry;
    },
    [fallbackStore],
  );

  useEffect(() => {
    const map = running.current;
    return () => {
      for (const entry of map.values()) entry.instance?.dispose();
      map.clear();
    };
  }, []);

  const go = useCallback((next: Route) => {
    setRoute(next);
    if (typeof window !== 'undefined') window.history.pushState(null, '', urlFor(next));
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(routeFromUrl(window.location.search, listApps()));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const current = route.appId ? ensure(route.appId) : null;
  const instance = current?.instance ?? null;
  const tabId = route.appId ? route.tabId : null;

  // Tell the open application which tab is showing (also after it finishes starting).
  useEffect(() => {
    if (instance && tabId) instance.setTab?.(tabId);
  }, [instance, tabId]);

  // Follow tab changes the application makes by itself.
  const routeAppId = route.appId;
  useEffect(() => {
    if (!instance?.onTabChange || !routeAppId) return;
    return instance.onTabChange((id) => {
      const next: Route = { appId: routeAppId, tabId: id };
      setRoute(next);
      window.history.replaceState(null, '', urlFor(next));
    });
  }, [instance, routeAppId]);

  const onEdit = useCallback((edit: SceneEdit) => instance?.onEdit?.(edit), [instance]);

  if (!route.appId || !current) {
    return (
      <div className="flex h-full w-full flex-col bg-mil-bg font-mono text-mil-text">
        <Header onHome={() => go({ appId: null })} />
        <Landing apps={apps} onOpen={(def) => go({ appId: def.id, tabId: tabsOf(def)[0].id })} />
      </div>
    );
  }

  const def = getApp(route.appId)!;
  const tabs = tabsOf(def);
  const { Sidebar, Side, Bottom, Banner, Overlay } = instance ?? {};
  const appStore = current.store;

  return (
    <div className="flex h-full w-full flex-col bg-mil-bg font-mono text-mil-text">
      <Header onHome={apps.length > 1 ? () => go({ appId: null }) : undefined} appTitle={def.title}>
        {tabs.length > 1 && (
          <TabBar tabs={tabs} active={route.tabId} label={`${def.title} views`} onSelect={(id) => go({ appId: def.id, tabId: id })} />
        )}
        {Banner && <Banner />}
      </Header>

      <div className="flex min-h-0 flex-1">
        {Sidebar && (
          <aside
            className="w-[300px] shrink-0 overflow-y-auto border-r border-mil-border bg-mil-panel/60 p-3 md:w-[360px]"
            role="tabpanel"
            id="shell-tabpanel"
            aria-labelledby={`shell-tab-${route.tabId}`}
          >
            <Sidebar />
          </aside>
        )}
        <main className="relative min-w-0 flex-1">
          <CesiumCanvas store={appStore} onEdit={onEdit} onScreenUpBearing={setUpBearing} />
          <div className="pointer-events-none absolute inset-0">
            <ViewControls store={appStore} upBearingDeg={upBearing} />
            <div className="pointer-events-auto absolute right-3 top-20">
              <Inspector store={appStore} />
            </div>
            {current.error && (
              <div className="pointer-events-auto absolute left-1/2 top-16 -translate-x-1/2 rounded-sm border border-mil-red/60 bg-mil-panel px-4 py-2 text-xs text-mil-red">
                Could not start application: {current.error}
              </div>
            )}
          </div>
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

function Header({ onHome, appTitle, children }: { onHome?: () => void; appTitle?: string; children?: React.ReactNode }) {
  return (
    <header className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-mil-border bg-mil-panel px-4 py-1">
      <div className="flex items-center gap-2">
        {onHome ? (
          <button className="mil-label text-mil-amber hover:text-white" onClick={onHome} title="All applications" aria-label="All applications">
            {PRODUCT_NAME}
          </button>
        ) : (
          <span className="mil-label text-mil-amber">{PRODUCT_NAME}</span>
        )}
        {appTitle && (
          <>
            <span className="text-mil-dim" aria-hidden>
              /
            </span>
            <span className="mil-label text-white">{appTitle}</span>
          </>
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-4 gap-y-1">{children}</div>
    </header>
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
          id={`shell-tab-${t.id}`}
          aria-selected={t.id === active}
          aria-controls="shell-tabpanel"
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
