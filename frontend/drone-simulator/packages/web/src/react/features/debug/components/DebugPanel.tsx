import { useState, useEffect } from 'react';
import { Panel } from '../../../shared/components/Panel';
import { Button } from '../../../shared/components/Button';
import { useGameMethod } from '../../../hooks/useGameMethod';
import { useDebugInfo } from '../hooks/useDebugInfo';
import { useQualitySettings } from '../hooks/useQualitySettings';
import { QualityPresets } from './QualityPresets';
import { QualityControls } from './QualityControls';
import { Shield } from 'lucide-react';

export function DebugPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const { toggleCollisionDetection, setWind, setRandomWind, getWind, setMLCorrection, isMLCorrectionEnabled } = useGameMethod();
  const { collisionEnabled, fps } = useDebugInfo();
  const { config, updateSetting, applyPreset } = useQualitySettings();

  const [windDir, setWindDir] = useState(0);
  const [windSpeed, setWindSpeed] = useState(0);
  const [windTurb, setWindTurb] = useState(0);
  const [mlEnabled, setMlEnabled] = useState(false);

  // Sync wind state
  useEffect(() => {
    if (!isOpen) return;
    const id = setInterval(() => {
      const w = getWind();
      setWindDir(Math.round(w.direction));
      setWindSpeed(Math.round(w.speed));
      setWindTurb(Math.round(w.turbulence * 100) / 100);
      setMlEnabled(isMLCorrectionEnabled());
    }, 500);
    return () => clearInterval(id);
  }, [isOpen]);

  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      if (e.key === '`' || e.key === '~') {
        e.preventDefault();
        setIsOpen(prev => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, []);

  const applyWind = (d: number, s: number, t: number) => {
    setWindDir(d); setWindSpeed(s); setWindTurb(t);
    setWind(d, s, t);
  };

  const speedLabel = windSpeed <= 5 ? 'CALM' : windSpeed <= 15 ? 'BREEZE' : windSpeed <= 30 ? 'GALE' : 'STORM';

  return (
    <>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed top-10 left-8 z-50 w-10 h-10 flex items-center justify-center
                   glass-panel hover:bg-mil-border/30 transition-all duration-200
                   text-mil-dim hover:text-mil-cyan text-sm font-mono group"
        title="Toggle Calibration Panel (`)"
      >
        <span className="group-hover:scale-110 transition-transform">~</span>
      </button>

      {isOpen && (
        <div className="fixed top-[84px] left-8 z-50 animate-slide-in max-h-[calc(100vh-120px)] overflow-y-auto pointer-events-auto">
          <Panel title="CALIBRATION" className="min-w-[280px] max-w-[320px]">
            <div className="space-y-4">
              {/* FPS */}
              <div className="flex items-center justify-between">
                <span className="mil-label">FPS</span>
                <span className={`font-mono font-semibold text-lg ${
                  fps >= 50 ? 'text-mil-green' : fps >= 30 ? 'text-mil-amber' : 'text-mil-red'
                }`}>
                  {fps}
                </span>
              </div>

              {/* Quality */}
              <div className="border-t border-mil-border pt-4">
                <QualityPresets onApplyPreset={applyPreset} />
              </div>

              <div className="border-t border-mil-border pt-4">
                <QualityControls config={config} onUpdateSetting={updateSetting} />
              </div>

              {/* Systems */}
              <div className="border-t border-mil-border pt-4 space-y-2">
                <div className="mil-label mb-2">SYSTEMS</div>
                <Button
                  onClick={toggleCollisionDetection}
                  variant={collisionEnabled ? 'primary' : 'secondary'}
                  size="sm"
                  className="w-full"
                >
                  <Shield size={14} className="inline mr-1.5" /> COLLISION {collisionEnabled ? 'ON' : 'OFF'}
                </Button>
              </div>

              {/* Wind System */}
              <div className="border-t border-mil-border pt-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="mil-label text-mil-amber">WIND SYSTEM</span>
                  <span className="text-[9px] text-mil-cyan font-mono">{windSpeed} m/s {speedLabel}</span>
                </div>

                {/* Direction */}
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-[8px] text-white/40 font-mono">DIRECTION</span>
                    <span className="text-[9px] text-mil-cyan font-mono">{windDir}°</span>
                  </div>
                  <input type="range" min="0" max="360" value={windDir}
                    onChange={(e) => applyWind(Number(e.target.value), windSpeed, windTurb)}
                    className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
                </div>

                {/* Speed */}
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-[8px] text-white/40 font-mono">SPEED</span>
                    <span className="text-[9px] text-mil-cyan font-mono">{windSpeed} m/s</span>
                  </div>
                  <input type="range" min="0" max="50" value={windSpeed}
                    onChange={(e) => applyWind(windDir, Number(e.target.value), windTurb)}
                    className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
                </div>

                {/* Turbulence */}
                <div className="space-y-1">
                  <div className="flex justify-between">
                    <span className="text-[8px] text-white/40 font-mono">TURBULENCE</span>
                    <span className="text-[9px] text-mil-cyan font-mono">{(windTurb * 100).toFixed(0)}%</span>
                  </div>
                  <input type="range" min="0" max="100" value={windTurb * 100}
                    onChange={(e) => applyWind(windDir, windSpeed, Number(e.target.value) / 100)}
                    className="w-full h-1 bg-mil-border rounded-sm appearance-none cursor-pointer accent-mil-cyan" />
                </div>

                {/* Presets */}
                <div className="flex gap-1">
                  <button onClick={() => applyWind(0, 0, 0)}
                    className="flex-1 py-1 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:bg-mil-border/30 hover:text-white transition-all">
                    CALM
                  </button>
                  <button onClick={() => { setRandomWind(); const w = getWind(); applyWind(Math.round(w.direction), Math.round(w.speed), Math.round(w.turbulence * 100) / 100); }}
                    className="flex-1 py-1 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:bg-mil-border/30 hover:text-white transition-all">
                    RANDOM
                  </button>
                  <button onClick={() => applyWind(windDir, 40, 0.8)}
                    className="flex-1 py-1 text-[8px] font-mono tracking-wider text-mil-dim border border-mil-border rounded-sm hover:bg-mil-border/30 hover:text-white transition-all">
                    STORM
                  </button>
                </div>

                {/* ML Correction */}
                <button onClick={() => { const next = !mlEnabled; setMlEnabled(next); setMLCorrection(next); }}
                  className={`w-full py-2 text-[9px] font-mono font-bold tracking-[0.1em] uppercase rounded-sm border transition-all ${
                    mlEnabled
                      ? 'bg-mil-cyan/20 text-mil-cyan border-mil-cyan/50'
                      : 'text-mil-dim border-mil-border hover:border-mil-text'
                  }`}>
                  AUTO-CORRECTION: {mlEnabled ? 'ON' : 'OFF'}
                </button>
                {mlEnabled && (
                  <div className="text-[8px] text-mil-green font-mono text-center animate-pulse">
                    ML MODEL ACTIVE
                  </div>
                )}
              </div>

              <div className="border-t border-mil-border pt-3">
                <div className="text-[10px] text-mil-dim font-mono">
                  Press <kbd className="px-1 py-0.5 bg-mil-panel border border-mil-border rounded-sm text-mil-cyan">~</kbd> to close
                </div>
              </div>
            </div>
          </Panel>
        </div>
      )}
    </>
  );
}
