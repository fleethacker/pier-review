import { useEffect, useRef, useState } from 'react';
import type { SceneStore } from '../scene/store';
import type { SceneEdit } from '../scene/types';
import type { SceneRenderer } from './cesium/SceneRenderer';

interface Props {
  store: SceneStore;
  onEdit: (edit: SceneEdit) => void;
  onScreenUpBearing?: (deg: number) => void;
}

export function CesiumCanvas({ store, onEdit, onScreenUpBearing }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const onEditRef = useRef(onEdit);
  const onBearingRef = useRef(onScreenUpBearing);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  onEditRef.current = onEdit;
  onBearingRef.current = onScreenUpBearing;

  // One viewer for the page: creating a Cesium viewer is slow, so a tab switch hands it another store instead.
  const rendererRef = useRef<SceneRenderer | null>(null);
  const storeRef = useRef(store);
  storeRef.current = store;
  useEffect(() => {
    if (!host.current) return;
    const container = host.current;
    let renderer: SceneRenderer | null = null;
    let cancelled = false;
    // Cesium is most of the bundle; load it after the app shell has painted.
    import('./cesium/SceneRenderer')
      .then(({ SceneRenderer: Renderer }) => {
        if (cancelled) return;
        renderer = new Renderer(
          container,
          storeRef.current,
          (edit) => onEditRef.current(edit),
          (bearing) => onBearingRef.current?.(bearing),
        );
        rendererRef.current = renderer;
        setLoading(false);
        if (import.meta.env.DEV) {
          const r = renderer;
          (window as unknown as { __scene: unknown }).__scene = {
            get store() {
              return storeRef.current;
            },
            screenPositionOf: (id: string) => r.screenPositionOf(id),
            geometryReady: () => r.geometryReady,
            pickAtPage: (x: number, y: number) => r.pickAtPage(x, y),
          };
        }
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
      rendererRef.current = null;
      renderer?.dispose();
    };
  }, []);

  useEffect(() => {
    rendererRef.current?.setStore(store);
  }, [store]);

  if (error) {
    return <div className="p-6 font-mono text-sm text-mil-red">The 3D canvas could not start: {error}</div>;
  }
  return (
    <div className="relative h-full w-full">
      <div ref={host} className="h-full w-full" data-testid="scene-canvas" />
      {loading && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-xs text-mil-cyan">
          Loading 3D engine…
        </div>
      )}
    </div>
  );
}
