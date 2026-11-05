/** A reference (for example an NSTM 582 paragraph) shown next to a finding. */
export function Citation({ reference }: { reference: string | null | undefined }) {
  if (!reference) return null;
  return (
    <span className="inline-block rounded-sm border border-mil-border px-1 py-0.5 font-mono text-[9px] text-mil-dim">
      {reference}
    </span>
  );
}
