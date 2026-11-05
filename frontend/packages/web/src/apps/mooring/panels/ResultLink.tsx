import { useController } from './context';

/** A cited result id; opens the stored result so the number behind a claim can be checked. */
export function ResultLink({ id }: { id: string }) {
  const c = useController();
  return (
    <button
      className="rounded-sm border border-mil-border px-1 py-0.5 font-mono text-[9px] text-mil-cyan hover:border-mil-cyan/60"
      onClick={(e) => {
        e.stopPropagation();
        c.openOverlay({ kind: 'result', id });
      }}
      title="Open the stored result"
    >
      {id}
    </button>
  );
}
