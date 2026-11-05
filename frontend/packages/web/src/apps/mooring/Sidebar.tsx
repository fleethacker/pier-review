import { Button } from '../../shell/ui';
import { useController, useMooring } from './panels/context';
import { useUnitSystem } from './units';
import { AgentPanel } from './panels/AgentPanel';
import { EnvPanel } from './panels/EnvPanel';
import { LinesPanel } from './panels/LinesPanel';
import { MotionLauncher } from './panels/MotionLauncher';
import { RecommendPanel } from './panels/RecommendPanel';
import { ResultPanel } from './panels/ResultPanel';
import { ScenarioPanel } from './panels/ScenarioPanel';
import { SequencePanel } from './panels/SequencePanel';
import { SetupPanel } from './panels/SetupPanel';
import { StatusPanel } from './status/StatusPanel';
import { BerthVisionPanel } from './vision/BerthVisionPanel';

export function Sidebar() {
  useUnitSystem();
  const c = useController();
  const phase = useMooring((s) => s.phase);
  const error = useMooring((s) => s.error);
  const notice = useMooring((s) => s.notice);
  if (phase === 'loading') return <p className="p-3 text-xs text-mil-cyan">Loading reference data…</p>;
  if (phase === 'error') {
    return (
      <div className="p-3 text-xs text-mil-red">
        <p>Could not reach the modeling service.</p>
        <p className="mt-1 text-mil-dim">{error}</p>
        <p className="mt-2 text-mil-dim">Start the mocks with `make mock` from the repo root.</p>
        <Button size="sm" className="mt-3" onClick={() => void c.init()}>
          Retry
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {notice && (
        <div
          role="status"
          className="flex items-start justify-between gap-2 rounded-sm border border-mil-amber/40 bg-mil-amber/10 p-2 text-[11px] text-mil-amber"
        >
          <span>{notice}</span>
          <button aria-label="Dismiss message" className="text-mil-dim hover:text-white" onClick={() => c.state.set({ notice: null })}>
            ✕
          </button>
        </div>
      )}
      <SetupPanel />
      <BerthVisionPanel />
      <EnvPanel />
      <StatusPanel />
      <AgentPanel />
      <LinesPanel />
      <ResultPanel />
      <SequencePanel />
      <MotionLauncher />
      <RecommendPanel />
      <ScenarioPanel />
    </div>
  );
}
