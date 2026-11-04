import { useMooring } from './panels/context';
import { EnvPanel } from './panels/EnvPanel';
import { LinesPanel } from './panels/LinesPanel';
import { RecommendPanel } from './panels/RecommendPanel';
import { ResultPanel } from './panels/ResultPanel';
import { ScenarioPanel } from './panels/ScenarioPanel';
import { SetupPanel } from './panels/SetupPanel';

export function Sidebar() {
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
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {notice && <div className="rounded-sm border border-mil-amber/40 bg-mil-amber/10 p-2 text-[11px] text-mil-amber">{notice}</div>}
      <SetupPanel />
      <EnvPanel />
      <LinesPanel />
      <ResultPanel />
      <RecommendPanel />
      <ScenarioPanel />
    </div>
  );
}
