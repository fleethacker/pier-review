import { cn } from '../../lib/cn';
import type { Validity } from './types';

const VALIDITY_CLASS: Record<Validity['state'], string> = {
  valid: 'border-mil-green/50 text-mil-green',
  limited: 'border-mil-amber/50 text-mil-amber',
  invalid: 'border-mil-red/50 text-mil-red',
  unknown: 'border-mil-border text-mil-dim',
};

export function ValidityBadge({ validity, label }: { validity: Validity | null | undefined; label?: string }) {
  if (!validity) return null;
  return (
    <span className={cn('inline-block rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider', VALIDITY_CLASS[validity.state])}>
      {label ? `${label}: ` : ''}
      {validity.state}
    </span>
  );
}

export function ValidityReasons({ validity }: { validity: Validity | null | undefined }) {
  const reasons = validity?.reasons ?? [];
  if (!reasons.length) return null;
  return (
    <ul className="mt-1 space-y-1 text-[11px] text-mil-text">
      {reasons.map((r) => (
        <li key={r.code}>
          <span className="font-mono text-[10px] text-mil-amber">{r.code}</span> {r.message}
        </li>
      ))}
    </ul>
  );
}

export function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="mil-label mb-2 mt-4 text-[11px] first:mt-0">{children}</h3>;
}

export function ErrorLine({ text }: { text: string | null }) {
  return text ? (
    <p role="alert" className="mt-2 rounded-sm border border-mil-red/40 bg-mil-red/10 px-2 py-1 text-[11px] text-mil-red">
      {text}
    </p>
  ) : null;
}

export function Notice({ text }: { text: string | null }) {
  return text ? (
    <p role="status" className="mt-2 rounded-sm border border-mil-green/40 bg-mil-green/10 px-2 py-1 text-[11px] text-mil-green">
      {text}
    </p>
  ) : null;
}

export const chipBtn = (active: boolean) =>
  cn(
    'border px-2 py-1 font-mono text-[10px] uppercase tracking-wider focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-mil-cyan/60',
    active ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan' : 'border-mil-border text-mil-text hover:text-white',
  );
