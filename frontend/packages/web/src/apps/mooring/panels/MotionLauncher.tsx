import { Button, Panel } from '../../../shell/ui';
import { useController, useMooring } from './context';

/** Opens the motion view: a live berthing session from the current setup, or a replay of the recorded mock fixture. */
export function MotionLauncher() {
  const c = useController();
  const ready = useMooring((s) => !!s.berth && !!s.ship);
  return (
    <Panel title="Motion" className="space-y-2 p-4">
      <p className="text-[11px] text-mil-dim">Watch the ship berth: environment, tugs, lines, fittings and fenders, from the simulator's own state.</p>
      <div className="flex gap-2">
        <Button size="sm" onClick={() => c.motion.open()} disabled={!ready}>
          Open motion view
        </Button>
      </div>
      {!ready && <p className="text-[10px] text-mil-dim">Choose a berth and a ship first.</p>}
    </Panel>
  );
}
