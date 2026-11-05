import { useEffect, useRef, useState } from 'react';
import { inputClass } from '../../shell/ui';

interface Props {
  label: string;
  value: number | undefined;
  onCommit: (value: number | undefined) => void;
  step?: number;
  min?: number;
  max?: number;
  /** Blank means "not set" and commits `undefined`. */
  optional?: boolean;
  placeholder?: string;
  decimals?: number;
  /** Drop the visible label (it stays as the accessible name), for rows in a table. */
  compact?: boolean;
}

const show = (v: number | undefined, decimals?: number) =>
  v === undefined ? '' : String(decimals === undefined ? v : Number(v.toFixed(decimals)));

/**
 * A number box that only changes the scenario when you leave it or press Enter, so a half-typed value never
 * reaches the simulation. Escape or an unusable entry puts the old value back.
 */
export function NumField({ label, value, onCommit, step = 1, min, max, optional, placeholder, decimals, compact }: Props) {
  const [text, setText] = useState(show(value, decimals));
  const cancelled = useRef(false);
  useEffect(() => setText(show(value, decimals)), [value, decimals]);

  const commit = () => {
    if (cancelled.current) {
      cancelled.current = false;
      setText(show(value, decimals));
      return;
    }
    const trimmed = text.trim();
    if (trimmed === '') {
      if (optional) onCommit(undefined);
      else setText(show(value, decimals));
      return;
    }
    const n = Number(trimmed);
    if (!Number.isFinite(n) || (min !== undefined && n < min) || (max !== undefined && n > max)) {
      setText(show(value, decimals));
      return;
    }
    if (n !== value) onCommit(n);
    else setText(show(value, decimals));
  };

  return (
    <label className="block">
      {!compact && <span className="mil-label mb-1 block">{label}</span>}
      <input
        aria-label={compact ? label : undefined}
        type="number"
        className={inputClass}
        value={text}
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur();
          if (e.key === 'Escape') {
            cancelled.current = true;
            e.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}
