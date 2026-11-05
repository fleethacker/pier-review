import { cn } from '../../../lib/cn';

export type Parts = 1 | 2 | 3;

const OPTIONS: { value: Parts; label: string; hint: string }[] = [
  { value: 1, label: 'Single', hint: 'One part of rope' },
  { value: 2, label: '×2', hint: 'Tanker moor: two parts' },
  { value: 3, label: 'Doubled', hint: 'Doubled up: three parts' },
];

/** Single up, tanker moor, or doubled up: how many parts of rope the line carries. */
export function PartsControl({
  value,
  onChange,
  label,
  disabled,
}: {
  value: Parts;
  onChange: (parts: Parts) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div role="group" aria-label={label} className="flex">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.hint}
          disabled={disabled}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'h-7 flex-1 border font-mono text-[10px] uppercase disabled:opacity-40',
            value === o.value
              ? 'border-mil-cyan/60 bg-mil-cyan/20 text-mil-cyan'
              : 'border-mil-border bg-mil-bg text-mil-text hover:text-white',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
