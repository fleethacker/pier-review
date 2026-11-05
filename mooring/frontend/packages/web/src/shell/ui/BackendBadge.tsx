import { cn } from '../../lib/cn';

/** Loud for placeholder data so nobody mistakes mock numbers for real ones. */
export function BackendBadge({ backend, className }: { backend: string | null | undefined; className?: string }) {
  if (!backend) return null;
  const mock = backend === 'mock';
  return (
    <span
      title={mock ? 'Placeholder values from the mock backend, not validated physics.' : `Backend: ${backend}`}
      className={cn(
        'inline-block rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest',
        mock ? 'border-mil-amber/60 bg-mil-amber/10 text-mil-amber' : 'border-mil-border text-mil-text',
        className,
      )}
    >
      {mock ? 'mock data' : backend}
    </span>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string | null | undefined }) {
  if (!confidence) return null;
  const weak = confidence === 'mock' || confidence === 'estimated' || confidence === 'vision';
  return (
    <span
      className={cn(
        'inline-block rounded-sm border px-1 py-0.5 font-mono text-[9px] uppercase tracking-wider',
        weak ? 'border-mil-amber/40 text-mil-amber/90' : 'border-mil-border text-mil-text',
      )}
    >
      {confidence}
    </span>
  );
}
