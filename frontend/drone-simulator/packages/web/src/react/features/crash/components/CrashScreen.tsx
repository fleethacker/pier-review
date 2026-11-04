import { useState, useEffect } from 'react';
import { useGameEvent } from '../../../hooks/useGameEvent';
import { useGameMethod } from '../../../hooks/useGameMethod';
import { Button } from '../../../shared/components/Button';

export function CrashScreen() {
  const [isCrashed, setIsCrashed] = useState(false);
  const crashData = useGameEvent('crashed');
  const { restart } = useGameMethod();

  useEffect(() => {
    if (crashData) {
      setIsCrashed(crashData.crashed);
    }
  }, [crashData]);

  useEffect(() => {
    if (!isCrashed) return;

    const handleKeyPress = (e: KeyboardEvent) => {
      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault();
        restart();
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [isCrashed, restart]);

  if (!isCrashed) return null;

  return (
    <div className="fixed inset-0 z-[150] bg-black/70 backdrop-blur-sm flex items-center justify-center animate-fade-in">
      <div className="relative max-w-md w-full mx-4">
        <div className="glass-panel mil-brackets p-8 text-center space-y-6 border-mil-red/50 animate-border-pulse">
          {/* Warning icon */}
          <div className="flex justify-center mb-2">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ff1744" strokeWidth="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          </div>

          <div className="space-y-2">
            <div className="mil-label text-mil-red tracking-[0.3em] animate-blink">WARNING</div>
            <h2 className="text-xl font-bold text-mil-red tracking-wider">
              SYSTEM FAILURE
            </h2>
            <p className="text-mil-dim text-xs font-mono">
              Terrain collision detected. All systems offline.
            </p>
          </div>

          <div className="space-y-3 pt-2">
            <Button
              onClick={restart}
              variant="primary"
              size="lg"
              className="w-full tracking-[0.15em]"
            >
              REINITIALIZE SYSTEMS
            </Button>

            <div className="text-[10px] text-mil-dim font-mono">
              Press <kbd className="px-1.5 py-0.5 bg-mil-panel border border-mil-border rounded-sm text-mil-cyan font-mono text-[10px]">R</kbd> to reinitialize
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
