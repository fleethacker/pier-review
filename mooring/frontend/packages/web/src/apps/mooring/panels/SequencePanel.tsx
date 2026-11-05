import { Citation, Panel } from '../../../shell/ui';
import { IDS } from '../mapping';
import { useAgent, useController } from './context';

const ACTION_LABEL: Record<string, string> = {
  pass: 'Pass line',
  secure_pier: 'Secure ashore',
  hold: 'Hold',
  take_to_power: 'Take to power',
  double_up: 'Double up',
  tend: 'Tend',
};

export function SequencePanel() {
  const c = useController();
  const seq = useAgent((s) => s.plan?.sequence);
  if (!seq) return null;
  return (
    <Panel title={`Line sequence · ${seq.steps.length} steps · ${seq.crews_required} crews`} className="space-y-1.5 p-4">
      <ol className="space-y-1">
        {seq.steps.map((st) => (
          <li
            key={st.step}
            className="cursor-pointer rounded-sm border border-mil-border bg-mil-bg/60 p-1.5 text-[11px] hover:border-mil-cyan/50"
            onClick={() => st.line_number != null && c.host.store.select({ type: 'link', id: IDS.line(st.line_number) })}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-white">
                {st.step}. {ACTION_LABEL[st.action] ?? st.action}
                {st.line_number != null ? ` · line ${st.line_number}` : ''}
              </span>
              <span className="text-mil-dim">{st.station}</span>
            </div>
            <div className="text-mil-text">{st.trigger}</div>
            {st.caution && <div className="text-mil-amber">{st.caution}</div>}
            <Citation reference={st.reference} />
          </li>
        ))}
      </ol>
    </Panel>
  );
}
