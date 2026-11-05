import { cn } from '../../lib/cn';
import type { Status } from '../../scene/types';
import { STATUS_COLOR } from '../theme';

export function StatusChip({ status, label, className }: { status: Status; label?: string; className?: string }) {
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider', className)}
      style={{ color: STATUS_COLOR[status] }}
    >
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[status] }} />
      {label ?? (status === 'NONE' ? 'n/a' : status)}
    </span>
  );
}

/** Maps a severity from any application onto a status the shell can color. */
export function toStatus(value: string | null | undefined): Status {
  switch (value?.toUpperCase()) {
    case 'GREEN':
    case 'INFO':
    case 'OK':
      return 'GREEN';
    case 'AMBER':
    case 'WARN':
    case 'WARNING':
      return 'AMBER';
    case 'RED':
    case 'ERROR':
    case 'CRITICAL':
      return 'RED';
    default:
      return 'NONE';
  }
}
