import type { ReactNode } from 'react';
import type { Selection } from '../../../scene/types';
import { Panel, StatusChip } from '../../../shell/ui';
import { STATUS_COLOR } from '../../../shell/theme';
import { describeComponents, compass, shipComponents } from '../conditions';
import { ENV_COLORS, hasUsableAnalysis, IDS } from '../mapping';
import { fmt, useUnitSystem } from '../units';
import { useController, useMooring } from './context';

type Row = [label: string, value: string];

function Section({
  color,
  tag,
  value,
  rows,
  description,
}: {
  color: string;
  tag: string;
  value?: string;
  rows: Row[];
  description: string;
}) {
  return (
    <section className="border-l-2 pl-3" style={{ borderColor: color }} aria-label={tag}>
      <header className="flex items-baseline justify-between gap-2">
        <span className="mil-label" style={{ color }}>
          {tag}
        </span>
        {value && <span className="mil-value text-sm">{value}</span>}
      </header>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
        {rows.map(([label, v]) => (
          <div key={label} className="contents">
            <dt className="text-mil-dim">{label}</dt>
            <dd className="text-right text-white">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[10px] leading-relaxed text-mil-text">{description}</p>
    </section>
  );
}

function RowButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between gap-2 rounded-sm px-1 py-0.5 text-left text-[11px] hover:bg-mil-cyan/10"
    >
      {children}
    </button>
  );
}

const bearing = (deg: number) => `${fmt.deg(deg)} ${compass(deg)}`;

/** Names the same variables, in the same colors, as the arrows and labels on the canvas, and explains each one. */
export function DataKey() {
  useUnitSystem();
  const c = useController();
  const env = useMooring((s) => s.env);
  const berth = useMooring((s) => s.berth);
  const side = useMooring((s) => s.side);
  const lines = useMooring((s) => s.lines);
  const analysis = useMooring((s) => s.analysis.response);
  const tugs = useMooring((s) => s.tugAssignments);
  const select = (selection: Selection) => c.host.store.select(selection);

  if (!env) return null;

  const windTo = (env.wind_from_true_deg + 180) % 360;
  const windParts = berth ? describeComponents(shipComponents(windTo, env.wind_speed_kt, berth, side)) : null;
  const curParts = berth ? describeComponents(shipComponents(env.current_set_true_deg, env.current_speed_kt, berth, side)) : null;
  const results = new Map((hasUsableAnalysis(analysis) ? analysis?.result.lines ?? [] : []).map((l) => [l.line_number, l]));
  const level = env.water_level_mllw_ft;

  return (
    <Panel title="Data key" className="space-y-4 p-4">
      <p className="text-[10px] leading-relaxed text-mil-dim">
        Each block below has the name and color of the label on the canvas. Arrows point the way the wind or water moves.
      </p>

      <Section
        color={ENV_COLORS.wind}
        tag="WIND"
        value={fmt.kt(env.wind_speed_kt)}
        rows={[
          ['Speed', fmt.kt(env.wind_speed_kt)],
          ['Gust', fmt.kt(env.wind_gust_kt)],
          ['Blowing from', bearing(env.wind_from_true_deg)],
          ['Blowing toward', bearing(windTo)],
          ...(windParts ? ([['Across the ship', windParts.offPier], ['Along the ship', windParts.along]] as Row[]) : []),
        ]}
        description="Air moving over the hull and superstructure pushes the ship sideways and along its length. The arrow grows with speed. Lines are checked against the gust, not the steady speed."
      />

      <Section
        color={ENV_COLORS.current}
        tag="CURRENT"
        value={`${env.current_speed_kt.toFixed(1)} kt`}
        rows={[
          ['Speed', `${env.current_speed_kt.toFixed(1)} kt`],
          ['Flowing toward', bearing(env.current_set_true_deg)],
          ...(curParts ? ([['Across the ship', curParts.offPier], ['Along the ship', curParts.along]] as Row[]) : []),
        ]}
        description="Water flowing past the hull drags on the underwater body, so it acts on the whole draft. The arrow points where the water is going and grows with speed."
      />

      <Section
        color={ENV_COLORS.water}
        tag="WATER LEVEL"
        value={`${level >= 0 ? '+' : ''}${fmt.ft(level, 1)}`}
        rows={[
          ['Height above MLLW', `${level >= 0 ? '+' : ''}${fmt.ft(level, 1)}`],
          ['Tide', env.tide_stage ?? 'not given'],
          ['Source', env.source],
        ]}
        description="Height of the water above mean lower low water. It changes line length and lead. Whether a line tightens or slackens depends on attachment heights and installed length; recheck the assessed installation."
      />

      <section className="border-l-2 pl-3" style={{ borderColor: '#c9d6e6' }} aria-label="LINES">
        <header className="flex items-baseline justify-between">
          <span className="mil-label" style={{ color: '#c9d6e6' }}>
            LINES
          </span>
          <span className="mil-value text-sm">{lines.length}</span>
        </header>
        <div className="mt-2 space-y-0.5">
          {lines.length === 0 && <p className="text-[11px] text-mil-dim">No lines placed yet.</p>}
          {lines.map((l) => {
            const r = results.get(l.line_number);
            return (
              <RowButton key={l.line_number} onClick={() => select({ type: 'link', id: IDS.line(l.line_number) })}>
                <span className="text-white">
                  <span style={{ color: r ? STATUS_COLOR[r.status] : '#c9d6e6' }}>L{l.line_number}</span>{' '}
                  <span className="text-mil-text">
                    {(l.role ?? 'line').replace('_', ' ')}
                    {l.parts > 1 ? ` ×${l.parts}` : ''}
                  </span>
                </span>
                <span className="flex items-center gap-2 text-white">
                  {r ? fmt.pct(r.pct_wll) : '—'}
                  {r && <StatusChip status={r.status} label="" />}
                </span>
              </RowButton>
            );
          })}
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-mil-text">
          Each line is tagged with its number and its load as a share of working load (WLL). Green is under 80%, amber 80 to 100%, red over 100%. A dash means no usable assessment is available. Select a row to find the line on the canvas.
        </p>
      </section>

      {tugs.length > 0 && (
        <section className="border-l-2 pl-3" style={{ borderColor: '#e8a33d' }} aria-label="TUGS">
          <header className="flex items-baseline justify-between">
            <span className="mil-label" style={{ color: '#e8a33d' }}>
              TUGS
            </span>
            <span className="mil-value text-sm">{tugs.length}</span>
          </header>
          <div className="mt-2 space-y-0.5">
            {tugs.map((t) => (
              <RowButton key={`${t.tug_id}:${t.push_point_id}`} onClick={() => select({ type: 'entity', id: `tug:${t.tug_id}:${t.push_point_id}` })}>
                <span className="text-white">
                  {t.tug_id} <span className="text-mil-text">{t.mode}</span>
                </span>
                <span className="text-right text-white">
                  {fmt.lbf(t.force_lbf)}
                  {t.direction_true_deg != null && <span className="text-mil-text"> toward {bearing(t.direction_true_deg)}</span>}
                </span>
              </RowButton>
            ))}
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-mil-text">
            Each tug sits at its push point. Its arrow points the way it pushes and is labeled with the force.
          </p>
        </section>
      )}
    </Panel>
  );
}
