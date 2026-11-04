export function ModeIndicator() {
  return (
    <div className="flex items-center gap-3 px-5 py-2.5 glass-panel">
      <div className="w-1.5 h-1.5 rounded-full bg-future-primary animate-pulse-subtle" />
      <span className="text-xs font-medium text-white/80 tracking-wide">
        X-47B Drone
      </span>
    </div>
  );
}
