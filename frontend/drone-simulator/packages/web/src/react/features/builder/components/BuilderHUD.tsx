import { useState, useEffect } from 'react';
import { useGameMethod } from '../../../hooks/useGameMethod';

interface BuilderHUDProps {
  onExecuteMission?: () => void;
}

export function BuilderHUD({ onExecuteMission }: BuilderHUDProps) {
  const { getWaypointCount, getWaypointPositions, clearWaypoints, getFlightProfiles, setFlightProfile } = useGameMethod();
  const [selectedProfile, setSelectedProfile] = useState('recon');
  const [tick, setTick] = useState(0);
  const profiles = getFlightProfiles();
  const wpCount = getWaypointCount();
  const waypoints = getWaypointPositions();

  // Poll for waypoint changes (Cesium-side state isn't reactive)
  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), 500);
    return () => clearInterval(id);
  }, []);

  const handleClear = () => {
    clearWaypoints();
    setTick(n => n + 1);
  };

  return (
    <div className="fixed top-10 left-1/2 -translate-x-1/2 z-50 pointer-events-auto animate-fade-in w-[420px]">
      <div className="glass-panel mil-brackets px-5 py-3">
        <div className="flex flex-col gap-3">
          {/* Header */}
          <div className="flex items-center justify-between gap-6">
            <div className="flex items-center gap-3">
              <div className="w-1.5 h-1.5 rounded-full bg-mil-amber animate-pulse-subtle" />
              <span className="mil-label text-mil-amber tracking-[0.2em]">MISSION PLANNING</span>
            </div>
            <div className="text-[10px] text-white/70 font-mono">
              Press <kbd className="px-1.5 py-0.5 bg-mil-panel border border-mil-border rounded-sm text-mil-cyan text-[9px]">B</kbd> to exit
            </div>
          </div>

          {/* Controls hint */}
          <div className="text-[9px] text-white/70 font-mono border-t border-mil-border pt-2 tracking-wider">
            WASD move cursor &bull; ↑↓ altitude &bull;
            <kbd className="px-1 py-0.5 bg-mil-panel border border-mil-border rounded-sm text-mil-cyan mx-0.5">SPACE</kbd> place WP &bull;
            <kbd className="px-1 py-0.5 bg-mil-panel border border-mil-border rounded-sm text-mil-cyan mx-0.5">ENTER</kbd> execute
          </div>

          {/* Waypoint list */}
          {wpCount > 0 && (
            <div className="border-t border-mil-border pt-2 space-y-1">
              <div className="flex items-center justify-between">
                <span className="mil-label">{wpCount} WAYPOINTS</span>
                <button
                  onClick={handleClear}
                  className="text-[9px] text-mil-red font-mono hover:text-mil-red/80 transition-colors tracking-wider"
                >
                  CLEAR ALL
                </button>
              </div>
              <div className="max-h-24 overflow-y-auto space-y-0.5">
                {waypoints.map((wp, i) => (
                  <div key={i} className="text-[9px] text-white/70 font-mono flex gap-2">
                    <span className="text-mil-cyan">WP-{String(i + 1).padStart(2, '0')}</span>
                    <span>{wp.lat.toFixed(4)}, {wp.lon.toFixed(4)}</span>
                    <span className="text-white/70">{Math.round(wp.alt)}m</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Flight profile selector - always visible */}
          <div className="border-t border-mil-border pt-2 space-y-1.5">
            <span className="mil-label">FLIGHT PROFILE</span>
            <div className="grid grid-cols-5 gap-1">
              {profiles.map((p) => (
                <button
                  key={p.id}
                  onClick={() => { setSelectedProfile(p.id); setFlightProfile(p.id); }}
                  className={`py-1.5 text-[8px] font-mono font-bold tracking-wider rounded-sm border transition-all ${
                    selectedProfile === p.id
                      ? 'bg-mil-cyan/20 text-mil-cyan border-mil-cyan/50'
                      : 'text-white/70 border-mil-border hover:border-mil-text hover:text-mil-text'
                  }`}
                  title={p.description}
                >
                  {p.id === 'noe' ? 'NOE' : p.id === 'stealth' ? 'STLTH' : p.id === 'recon' ? 'RECON' : p.id === 'safe' ? 'HIGH' : 'FAST'}
                </button>
              ))}
            </div>
            <div className="text-[8px] text-white/70 font-mono">
              {profiles.find(p => p.id === selectedProfile)?.description}
            </div>
          </div>

          {/* Execute button */}
          {wpCount >= 1 && (
            <button
              onClick={onExecuteMission}
              className="w-full py-2 text-[10px] font-mono font-bold tracking-[0.15em] uppercase
                         bg-mil-green/20 hover:bg-mil-green/30 text-mil-green border border-mil-green/40
                         hover:border-mil-green/60 rounded-sm transition-all"
            >
              EXECUTE MISSION
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
