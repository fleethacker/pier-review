interface ControlButtonProps {
  keys: string[];
  description: string;
}

export function ControlButton({ keys, description }: ControlButtonProps) {
  return (
    <div className="flex items-center justify-between gap-3 group">
      <div className="flex gap-1.5">
        {keys.map((key) => (
          <kbd
            key={key}
            className="px-2 py-1 text-[10px] font-mono font-medium text-mil-cyan bg-mil-panel border border-mil-border rounded-sm group-hover:bg-mil-border/30 group-hover:border-mil-cyan/30 transition-all"
          >
            {key}
          </kbd>
        ))}
      </div>
      <span className="text-xs text-mil-dim group-hover:text-mil-text transition-colors font-mono">{description}</span>
    </div>
  );
}
