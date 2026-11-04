import { useEffect, useRef, useState } from 'react';
import type { SceneStore } from '../scene/store';
import type { SceneEdit } from '../scene/types';
import { SceneRenderer } from './cesium/SceneRenderer';

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
  onEditRef.current = onEdit;
  onBearingRef.current = onScreenUpBearing;

  useEffect(() => {
    if (!host.current) return;
    let renderer: SceneRenderer | null = null;
    try {
      renderer = new SceneRenderer(
        host.current,
        store,
        (edit) => onEditRef.current(edit),
        (bearing) => onBearingRef.current?.(bearing),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    return () => renderer?.dispose();
  }, [store]);

  if (error) {
    return <div className="p-6 font-mono text-sm text-mil-red">The 3D canvas could not start: {error}</div>;
  }
  return <div ref={host} className="h-full w-full" data-testid="scene-canvas" />;
}
