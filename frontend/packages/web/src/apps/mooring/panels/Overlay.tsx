import { useEffect, useRef, useState } from 'react';
import { cn } from '../../../lib/cn';
import { BackendBadge, Button, Citation, Field, Panel, Select, StatusChip, inputClass, toStatus } from '../../../shell/ui';
import { fetchResult } from '../agent';
import type { Role } from '../agent';
import { fmt, useUnitSystem } from '../units';
import { useAgent, useController, useMooring } from './context';
import { ResultLink } from './ResultLink';

export function Overlay() {
  useUnitSystem();
  const overlay = useMooring((s) => s.overlay);
  if (!overlay) return null;
  return overlay.kind === 'result' ? <ResultViewer id={overlay.id} /> : <SheetViewer />;
}

function Frame({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="pointer-events-auto flex h-full w-full items-start justify-center overflow-auto bg-mil-bg/80 p-6" role="dialog" aria-label={title}>
      <div className={cn('w-full', wide ? 'max-w-6xl' : 'max-w-3xl')}>
        <Panel className="p-0">
          <div className="flex items-center justify-between border-b border-mil-border px-4 py-2">
            <span className="mil-label">{title}</span>
            <Button size="sm" variant="ghost" onClick={onClose}>
              Close
            </Button>
          </div>
          <div className="p-4">{children}</div>
        </Panel>
      </div>
    </div>
  );
}

interface Envelope {
  result_id: string;
  model: string;
  model_version: string;
  backend: string;
  status: 'GREEN' | 'AMBER' | 'RED';
  computed_at_utc: string;
  inputs_hash: string;
  assumptions?: string[];
  warnings?: { rule_id: string; severity: string; message: string; reference: string }[];
  result: unknown;
}

function ResultViewer({ id }: { id: string }) {
  const c = useController();
  const [data, setData] = useState<Envelope | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    fetchResult(id)
      .then((d) => live && setData(d as Envelope))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [id]);
  return (
    <Frame title={`Result ${id}`} onClose={() => c.openOverlay(null)}>
      {error && <p className="text-xs text-mil-red">{error}</p>}
      {!data && !error && <p className="text-xs text-mil-cyan">Loading…</p>}
      {data && (
        <div className="space-y-3 text-xs">
          <div className="flex items-center justify-between">
            <StatusChip status={data.status} />
            <BackendBadge backend={data.backend} />
          </div>
          <dl className="grid grid-cols-[120px_1fr] gap-y-1">
            <dt className="text-mil-dim">Model</dt>
            <dd className="text-white">
              {data.model} {data.model_version}
            </dd>
            <dt className="text-mil-dim">Computed</dt>
            <dd className="text-white">{data.computed_at_utc}</dd>
            <dt className="text-mil-dim">Inputs hash</dt>
            <dd className="break-all text-white">{data.inputs_hash}</dd>
          </dl>
          {(data.warnings ?? []).map((w, i) => (
            <div key={i} className="flex items-center gap-2">
              <StatusChip status={toStatus(w.severity)} label="" />
              <span className="text-white">{w.message}</span>
              <Citation reference={w.reference} />
            </div>
          ))}
          <details>
            <summary className="cursor-pointer text-mil-dim">Assumptions</summary>
            <ul className="mt-1 list-disc pl-4 text-mil-text">
              {(data.assumptions ?? []).map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </details>
          <pre className="max-h-96 overflow-auto rounded-sm border border-mil-border bg-mil-bg p-3 text-[10px] text-mil-text">
            {JSON.stringify(data.result, null, 2)}
          </pre>
        </div>
      )}
    </Frame>
  );
}

const ROLES: { value: Role; label: string }[] = [
  { value: 'pilot', label: 'Pilot' },
  { value: 'first_lt', label: 'First Lieutenant' },
  { value: 'co', label: 'Commanding Officer' },
];

function SheetViewer() {
  const c = useController();
  const sheet = useAgent((s) => s.sheet);
  const iframe = useRef<HTMLIFrameElement>(null);
  const [role, setRole] = useState<Role>('pilot');
  const [name, setName] = useState('');
  const [comment, setComment] = useState('');
  const s = sheet.sheet;
  if (!s) return null;
  const approved = s.approvals.filter((a) => a.decision === 'approve');
  const rejected = s.approvals.some((a) => a.decision === 'reject');

  return (
    <Frame title={`Mooring Evolution Safety Sheet · v${s.version}`} onClose={() => c.openOverlay(null)} wide>
      <div className="grid grid-cols-[1fr_340px] gap-4">
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <StatusChip status={s.status} label={`Plan ${s.status}`} />
            <div className="flex items-center gap-2">
              {s.sources.some((x) => x.confidence === 'mock') && <BackendBadge backend="mock" />}
              <Button size="sm" variant="secondary" onClick={() => iframe.current?.contentWindow?.print()}>
                Print
              </Button>
            </div>
          </div>
          <iframe
            ref={iframe}
            title="Safety sheet"
            sandbox="allow-same-origin allow-modals"
            srcDoc={sheet.html ?? ''}
            className="h-[62vh] w-full rounded-sm border border-mil-border bg-white"
          />
          <p className="text-[10px] text-mil-dim">{s.disclaimer}</p>
        </div>

        <div className="space-y-3 text-[11px]">
          {sheet.image && (
            <div>
              <div className="mil-label mb-1">Layout</div>
              <img src={sheet.image} alt="Mooring layout at the time the sheet was built" className="w-full rounded-sm border border-mil-border" />
              <a className="mt-1 inline-block text-mil-cyan underline" href={sheet.image} download={`mooring-layout-${s.sheet_id}.jpg`}>
                Download layout image
              </a>
            </div>
          )}

          {s.warnings.length > 0 && (
            <div>
              <div className="mil-label mb-1">Warnings</div>
              {s.warnings.map((w, i) => (
                <div key={i} className="mb-1 flex items-start gap-2">
                  <StatusChip status={toStatus(w.severity)} label="" className="mt-0.5" />
                  <span className="text-white">{w.message}</span>
                  <Citation reference={w.reference} />
                </div>
              ))}
            </div>
          )}

          <div>
            <div className="mil-label mb-1">Safety margins</div>
            <ul className="space-y-0.5">
              {s.line_plan.map((l) => (
                <li key={l.line_number} className="flex items-center justify-between text-white">
                  <span>
                    Line {l.line_number} {l.role}
                  </span>
                  <span className="flex items-center gap-2">
                    {fmt.pct(l.pct_wll)} of WLL <StatusChip status={l.status} label="" />
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <div className="mil-label mb-1">Rationale (cited results)</div>
            {s.rationale.map((r) => (
              <p key={r.text} className="mb-1 text-white">
                {r.text}
                <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
                  {r.cites.map((id) => (
                    <ResultLink key={id} id={id} />
                  ))}
                </span>
              </p>
            ))}
          </div>

          <div className="space-y-2 border-t border-mil-border pt-3">
            <div className="mil-label">Approvals {s.locked && <span className="text-mil-dim">(sheet locked)</span>}</div>
            {s.approvals.length === 0 && <p className="text-mil-dim">No approvals yet.</p>}
            {s.approvals.map((a) => (
              <div key={`${a.role}-${a.at_utc}`} className="flex items-center justify-between text-white">
                <span>
                  {ROLES.find((r) => r.value === a.role)?.label}: {a.name}
                  {a.comment ? ` — ${a.comment}` : ''}
                </span>
                <StatusChip status={a.decision === 'approve' ? 'GREEN' : 'RED'} label={a.decision} />
              </div>
            ))}
            <p className={rejected ? 'text-mil-red' : approved.length >= 1 ? 'text-mil-green' : 'text-mil-dim'}>
              {rejected ? 'Rejected: do not execute this plan.' : approved.length >= 1 ? `${approved.length} approval(s) recorded.` : 'Awaiting approval.'}
            </p>
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                void c.agent.approve(role, name.trim(), 'approve', comment.trim());
                setName('');
                setComment('');
              }}
            >
              <Field label="Role">
                <Select value={role} onChange={(v) => setRole(v as Role)} options={ROLES} />
              </Field>
              <Field label="Name">
                <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Comment">
                <input className={inputClass} value={comment} onChange={(e) => setComment(e.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button size="sm" type="submit" disabled={!name.trim()}>
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  type="button"
                  disabled={!name.trim()}
                  onClick={() => void c.agent.approve(role, name.trim(), 'reject', comment.trim())}
                >
                  Reject
                </Button>
              </div>
            </form>
            {sheet.error && <p className="text-mil-red">{sheet.error}</p>}
          </div>
        </div>
      </div>
    </Frame>
  );
}
