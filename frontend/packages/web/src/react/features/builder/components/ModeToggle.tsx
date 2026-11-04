import { useGameMode } from '../../../hooks/useGameMode';

export function ModeToggle() {
  const { mode, toggleBuilder } = useGameMode();

  return (
    <button
      onClick={toggleBuilder}
      className="glass-panel px-4 py-2.5 hover:bg-mil-border/30 transition-all duration-200
                 text-mil-text hover:text-white text-[10px] font-mono font-medium tracking-wider uppercase
                 flex items-center gap-2 group"
      title={mode === 'play' ? 'Mission Planning (B)' : 'Return to Ops (B)'}
    >
      <div className={`w-1.5 h-1.5 rounded-full ${mode === 'builder' ? 'bg-mil-amber' : 'bg-mil-cyan'} animate-pulse-subtle`} />
      <span>{mode === 'play' ? 'MISSION' : 'OPS'}</span>
    </button>
  );
}
