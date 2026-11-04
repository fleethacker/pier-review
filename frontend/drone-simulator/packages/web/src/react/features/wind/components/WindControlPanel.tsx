import { useState, useEffect } from 'react';
import { useGameMethod } from '../../../hooks/useGameMethod';

export function WindControlPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const { setWind, setRandomWind, getWind, setMLCorrection, isMLCorrectionEnabled } = useGameMethod();

  const [direction, setDirection] = useState(0);
  const [speed, setSpeed] = useState(0);
  const [turbulence, setTurbulence] = useState(0);
  const [mlEnabled, setMlEnabled] = useState(false);

  // Sync from game state periodically
  useEffect(() => {
    const id = setInterval(() => {
      const w = getWind();
      setDirection(Math.round(w.direction));
      setSpeed(Math.round(w.speed));
      setTurbulence(Math.round(w.turbulence * 100) / 100);
      setMlEnabled(isMLCorrectionEnabled());
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const applyWind = (d: number, s: number, t: number) => {
    setDirection(d);
    setSpeed(s);
    setTurbulence(t);
    setWind(d, s, t);
  };

  const handleRandom = () => {
    setRandomWind();
    const w = getWind();
    setDirection(Math.round(w.direction));
    setSpeed(Math.round(w.speed));
    setTurbulence(Math.round(w.turbulence * 100) / 100);
  };

  const handleCalm = () => applyWind(0, 0, 0);

  const handleMLToggle = () => {
    const next = !mlEnabled;
    setMlEnabled(next);
    setMLCorrection(next);
  };

  const speedLabel = speed <= 5 ? 'CALM' : speed <= 15 ? 'BREEZE' : speed <= 30 ? 'GALE' : 'STORM';
  const turbLabel = turbulence <= 0.2 ? 'NONE' : turbulence <= 0.5 ? 'LIGHT' : turbulence <= 0.8 ? 'MODERATE' : 'SEVERE';

  return (
    <>
      {/* Toggle button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed top-10 left-[72px] z-50 w-10 h-10 flex items-center justify-center
                   glass-panel hover:bg-mil-border/30 transition-all duration-200
                   text-mil-dim hover:text-mil-cyan text-sm font-mono group pointer-events-auto"
        title="Wind Controls"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M9.59 4.59A2 2 0 1 1 11 8H2m10.59 11.41A2 2 0 1 0 14 16H2m15.73-8.27A2.5 2.5 0 1 1 19.5 12H2" />
        </svg>
      </button>

      {isOpen && (
        <div className="fixed top-[84px] left-[72px] z-50 w-64 pointer-events-auto animate-fade-in">
          <div className="glass-panel mil-brackets p-4 space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
              <span className="mil-label text-mil-amber">WIND SYSTEM</span>
              <div className="flex items-center gap-1">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                     style={{ transform: `rotate(${direction}deg)` }} className="text-mil-cyan">
                  <path d="M12 2l4 8H8z" fill="currentColor" />
                  <line x1="12" y1="10" x2="12" y2="22" />
                </svg>
                <span className="text-[10px] text-mil-cyan font-mono">{speed} m/s</span>
              </div>
            </div>

            {/* Direction */}
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-[9px] text-white/50 font-mono">DIRECTION</span>
                <span className="text-[9px] text-mil-cyan font-mono">{direction}°</span>
              </div>
              <input type="range" min="0" max="360" value={direction}
                onChange={(e) => applyWind(Number(e.target.value), speed, turbulence)}
                className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
            </div>

            {/* Speed */}
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-[9px] text-white/50 font-mono">SPEED</span>
                <span className="text-[9px] text-mil-cyan font-mono">{speed} m/s — {speedLabel}</span>
              </div>
              <input type="range" min="0" max="50" value={speed}
                onChange={(e) => applyWind(direction, Number(e.target.value), turbulence)}
                className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
            </div>

            {/* Turbulence */}
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-[9px] text-white/50 font-mono">TURBULENCE</span>
                <span className="text-[9px] text-mil-cyan font-mono">{turbulence} — {turbLabel}</span>
              </div>
              <input type="range" min="0" max="100" value={turbulence * 100}
                onChange={(e) => applyWind(direction, speed, Number(e.target.value) / 100)}
                className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
            </div>

            {/* Presets */}
            <div className="flex gap-1 border-t border-mil-border pt-2">
              <button onClick={handleCalm}
                className="flex-1 py-1.5 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:bg-mil-border/30 hover:text-white transition-all">
                CALM
              </button>
              <button onClick={handleRandom}
                className="flex-1 py-1.5 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:bg-mil-border/30 hover:text-white transition-all">
                RANDOM
              </button>
              <button onClick={() => applyWind(direction, 40, 0.8)}
                className="flex-1 py-1.5 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:bg-mil-border/30 hover:text-white transition-all">
                STORM
              </button>
            </div>

            {/* ML Correction Toggle */}
            <div className="border-t border-mil-border pt-2">
              <button onClick={handleMLToggle}
                className={`w-full py-2 text-[9px] font-mono font-bold tracking-[0.1em] uppercase rounded-sm border transition-all ${
                  mlEnabled
                    ? 'bg-mil-cyan/20 text-mil-cyan border-mil-cyan/50'
                    : 'text-mil-dim border-mil-border hover:border-mil-text'
                }`}>
                AUTO-CORRECTION: {mlEnabled ? 'ON' : 'OFF'}
              </button>
              {mlEnabled && (
                <div className="text-[8px] text-mil-green font-mono mt-1 text-center animate-pulse">
                  ML MODEL ACTIVE
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
