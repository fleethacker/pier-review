import { cn } from '../../../lib/cn';
import { Button, Panel } from '../../../shell/ui';
import { STATUS_COLOR } from '../../../shell/theme';
import { useController, useMooring } from '../panels/context';
import { deriveSources, formatAge, limitedCount } from './sources';
import type { SourceState } from './sources';

const STATE_STYLE: Record<SourceState, { color: string; label: string }> = {
  live: { color: STATUS_COLOR.GREEN, label: 'live' },
  prediction: { color: '#38bdf8', label: 'prediction' },
  replay: { color: '#a78bfa', label: 'replay' },
  mock: { color: STATUS_COLOR.AMBER, label: 'mock' },
  manual: { color: '#8ba4c4', label: 'typed' },
  unavailable: { color: STATUS_COLOR.RED, label: 'unavailable' },
  error: { color: STATUS_COLOR.RED, label: 'error' },
};

/** Where each data stream comes from, how old it is and why it is not live; plus what each capability is qualified for. */
export function StatusPanel() {
  const c = useController();
  const env = useMooring((s) => s.env);
  const envMode = useMooring((s) => s.envMode);
  const capabilities = useMooring((s) => s.capabilities);
  const modules = useMooring((s) => s.modules);
  const apiVersion = useMooring((s) => s.apiVersion);
  const catalogOk = useMooring((s) => s.catalogOk);
  const statusError = useMooring((s) => s.statusError);
  const backend = useMooring((s) => s.backend);
  const envError = useMooring((s) => s.envError);
  const rows = deriveSources({ env, envMode, capabilities, envError });
  const { limited, total } = limitedCount(capabilities);
  return (
    <Panel title="Data sources and capabilities" className="space-y-2 p-4">
      <ul className="space-y-1.5" aria-label="Data sources">
        {rows.map((r) => {
          const st = STATE_STYLE[r.state];
          return (
            <li key={r.id} className="text-[11px]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-mil-text">{r.label}</span>
                <span className="flex items-center gap-2">
                  {(r.state === 'live' || r.state === 'replay' || r.state === 'prediction') && <span className="text-[10px] text-mil-dim">{formatAge(r.ageS)}</span>}
                  <span className="rounded-sm border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider" style={{ color: st.color, borderColor: `${st.color}66` }}>
                    {st.label}
                  </span>
                </span>
              </div>
              <div className="text-[10px] text-mil-dim">
                {r.provider}
                {r.basis ? ` · basis ${r.basis}` : ''}
                {r.quality && r.quality !== 'good' ? ` · quality ${r.quality}` : ''}
                {r.reason ? ` · ${r.reason}` : ''}
              </div>
            </li>
          );
        })}
      </ul>

      <div className="border-t border-mil-border pt-2 text-[10px] text-mil-dim">
        <span className="text-mil-amber">Bollard structural strain: unavailable.</span>{' '}
        Fitting load and percentage of capacity do not measure deformation. A reviewed structural model and asset properties are required.
      </div>

      {statusError && (
        <div role="alert" className="rounded-sm border border-mil-red/40 bg-mil-red/10 p-2 text-[10px] text-mil-red">
          Could not read the service's capability statement: {statusError}
          <Button size="sm" variant="ghost" className="ml-2" onClick={() => void c.loadStatus()}>
            Retry
          </Button>
        </div>
      )}

      <details className="text-[11px]">
        <summary className="cursor-pointer text-mil-dim">
          Capabilities{capabilities ? `: ${limited} of ${total} not qualified` : ''} · service backend: {backend ?? 'unknown'}
          {apiVersion ? ` · API ${apiVersion}` : ''}
        </summary>
        {capabilities ? (
          <ul className="mt-2 space-y-2">
            {capabilities.map((cap) => (
              <li key={cap.capability}>
                <div className="flex items-start justify-between gap-2">
                  <span>{cap.capability}</span>
                  <span
                    className={cn('shrink-0 font-mono text-[10px] uppercase', cap.qualification === 'qualified' ? 'text-mil-green' : 'text-mil-amber')}
                    title={`${cap.module} · backend ${cap.backend}`}
                  >
                    {cap.backend} · {cap.qualification}
                  </span>
                </div>
                {cap.limitations.map((l, i) => (
                  <div key={`${i}-${l}`} className="text-[10px] text-mil-dim">Limit: {l}</div>
                ))}
                {cap.blockers.map((b, i) => (
                  <div key={`${i}-${b}`} className="text-[10px] text-mil-red/80">Blocker: {b}</div>
                ))}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[10px] text-mil-dim">{statusError ? 'Unavailable.' : 'Loading…'}</p>
        )}
        {catalogOk && (
          <p className={cn('mt-2 text-[10px]', catalogOk.ok ? 'text-mil-dim' : 'text-mil-red')}>
            Reference catalog audit: {catalogOk.ok ? 'no problems found (seed data stays unqualified)' : `${catalogOk.problems.length} problem(s): ${catalogOk.problems.slice(0, 3).join('; ')}`}
          </p>
        )}
        {modules && (
          <details className="mt-2 text-[10px] text-mil-dim">
            <summary className="cursor-pointer">Module status</summary>
            <ul className="mt-1">
              {Object.entries(modules).map(([k, v]) => (
                <li key={k}>{k}: {v}</li>
              ))}
            </ul>
          </details>
        )}
      </details>
    </Panel>
  );
}
