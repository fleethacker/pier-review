import type { ReactNode } from 'react';
import { cn } from '../../lib/cn';

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn('block', className)}>
      <span className="mil-label mb-1 block">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  'w-full rounded-sm border border-mil-border bg-mil-bg px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-mil-cyan/60';

export function Select({
  value,
  onChange,
  options,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; disabled?: boolean }[];
  disabled?: boolean;
}) {
  return (
    <select
      className={inputClass}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} disabled={o.disabled}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
