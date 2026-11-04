import { useState, useEffect, useCallback } from 'react';
import type { MaverickState } from '../hooks/useMaverickState';
import { useGameMethod } from '../../../hooks/useGameMethod';

const PHASE_LABELS: Record<string, string> = {
  cinematic: 'INITIALIZING...',
  briefing: 'MISSION BRIEFING',
  deck: 'ON DECK — APPLY THROTTLE',
  takeoff: 'TAKEOFF',
  transit: 'TRANSIT TO TARGET',
  canyon_run: 'CANYON RUN — STAY LOW',
  egress: 'EGRESS — EVADE SAMs',
  rtb: 'RETURN TO BASE',
  complete: 'MISSION COMPLETE',
  failed: 'MISSION FAILED',
};

export function MaverickHUD({ state }: { state: MaverickState }) {
  const { skipToTarget } = useGameMethod();
  const {
    phase,
    missionTime,
    chaff,
    flares,
    agl,
    altitudeWarning,
    samAlert,
    missileIncoming,
    lastDefeated,
    missilesEvaded,
  } = state;

  const [showSkip, setShowSkip] = useState(true);

  // Auto-hide skip button after 15 seconds
  useEffect(() => {
    if (phase === 'transit' || phase === 'takeoff') {
      setShowSkip(true);
      const timer = setTimeout(() => setShowSkip(false), 15000);
      return () => clearTimeout(timer);
    }
  }, [phase]);

  // T key to skip
  const handleSkip = useCallback(() => {
    skipToTarget();
    setShowSkip(false);
  }, [skipToTarget]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.code === 'KeyT' && (phase === 'transit' || phase === 'takeoff') && showSkip) {
        handleSkip();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [phase, showSkip, handleSkip]);

  if (phase === 'cinematic') return null;

  const minutes = Math.floor(missionTime / 60);
  const seconds = Math.floor(missionTime % 60);
  const timeStr = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

  const isCanyonPhase = phase === 'canyon_run' || phase === 'egress';

  return (
    <div className="fixed inset-0 pointer-events-none z-40 font-mono">
      {/* Mission phase banner — below the status bar header (32px + gap) */}
      <div className="absolute top-12 left-1/2 -translate-x-1/2 text-center">
        <div className={`text-xs tracking-[0.3em] px-6 py-2 border rounded-sm ${
          phase === 'canyon_run' || phase === 'egress'
            ? 'text-[#ff3333] border-[#ff3333]/30 bg-[#1a0a0a]/80'
            : 'text-[#00e5ff] border-[#00e5ff]/30 bg-[#0a1628]/80'
        }`}>
          {PHASE_LABELS[phase] || phase.toUpperCase()}
        </div>
        <div className="text-[10px] text-[#4a6a8a] mt-1 tracking-wider">
          T+{timeStr}
        </div>
      </div>

      {/* Skip to target button — during transit/takeoff, auto-hides after 15s */}
      {(phase === 'transit' || phase === 'takeoff') && showSkip && (
        <div className="fixed top-32 left-1/2 -translate-x-1/2 z-[200] pointer-events-auto">
          <button
            onClick={handleSkip}
            className="px-6 py-3 bg-[#ffc107]/20 border-2 border-[#ffc107]/60 text-[#ffc107]
                       text-xs tracking-[0.3em] font-mono font-bold rounded-sm
                       hover:bg-[#ffc107]/30 hover:border-[#ffc107] hover:text-white
                       transition-all cursor-pointer"
            style={{ textShadow: '0 0 10px rgba(255, 193, 7, 0.3)' }}
          >
            T — SKIP TO TARGET AREA
          </button>
        </div>
      )}

      {/* SAM WARNING — escalating warning based on threat state */}
      {samAlert && samAlert.type === 'tracking' && (
        <div className="fixed top-8 left-0 right-0 z-[100] flex justify-center">
          <div className="px-6 py-2 bg-[#ffc107]/20 border border-[#ffc107]/50 text-[#ffc107] text-xs font-mono tracking-[0.3em] animate-pulse">
            WARNING — ENEMY RADAR LOCK — DESCEND IMMEDIATELY
          </div>
        </div>
      )}
      {samAlert && samAlert.type === 'locked' && (
        <div className="fixed top-8 left-0 right-0 z-[100] flex justify-center">
          <div className="px-6 py-2 bg-[#ff3333]/30 border-2 border-[#ff3333]/70 text-[#ff3333] text-sm font-mono tracking-[0.3em] font-bold animate-pulse">
            MISSILE LOCK — EVADE NOW
          </div>
        </div>
      )}
      {samAlert && samAlert.type === 'firing' && (
        <>
          <div className="fixed top-8 left-0 right-0 h-1.5 bg-[#ff3333] animate-pulse z-[100]" />
          <div className="fixed top-10 left-0 right-0 z-[100] flex justify-center">
            <div className="px-6 py-2 bg-[#ff3333]/40 border-2 border-[#ff3333] text-white text-sm font-mono tracking-[0.3em] font-bold animate-pulse">
              MISSILE LAUNCHED — DEPLOY COUNTERMEASURES (Z/X)
            </div>
          </div>
        </>
      )}

      {/* Altitude AGL — left side */}
      {isCanyonPhase && (
        <div className={`absolute left-4 top-1/2 -translate-y-1/2 text-center ${
          altitudeWarning ? 'animate-pulse' : ''
        }`}>
          <div className={`text-[10px] tracking-wider ${
            altitudeWarning ? 'text-[#ff3333]' : 'text-[#4a6a8a]'
          }`}>AGL</div>
          <div className={`text-2xl font-bold ${
            altitudeWarning ? 'text-[#ff3333]' : agl < 100 ? 'text-[#ffc107]' : 'text-[#00e5ff]'
          }`}>
            {Math.round(agl)}
          </div>
          <div className={`text-[10px] ${
            altitudeWarning ? 'text-[#ff3333]' : 'text-[#4a6a8a]'
          }`}>METERS</div>
          {altitudeWarning && (
            <div className="text-[10px] text-[#ff3333] mt-1 animate-pulse tracking-wider">
              TOO HIGH
            </div>
          )}
        </div>
      )}

      {/* SAM Threat Warning — top right */}
      {samAlert && (
        <div className="absolute top-20 right-4 animate-pulse">
          <div className={`px-4 py-2 border rounded-sm ${
            samAlert.type === 'firing'
              ? 'text-[#ff3333] border-[#ff3333]/50 bg-[#1a0a0a]/90'
              : samAlert.type === 'locked'
              ? 'text-[#ff6633] border-[#ff6633]/50 bg-[#1a0a0a]/90'
              : 'text-[#ffc107] border-[#ffc107]/50 bg-[#1a1200]/90'
          }`}>
            <div className="text-[10px] tracking-[0.3em]">
              {samAlert.type === 'firing' ? 'MISSILE LAUNCH' :
               samAlert.type === 'locked' ? 'RADAR LOCK' : 'SAM TRACKING'}
            </div>
            <div className="text-xs mt-1">
              {Math.round(samAlert.distance)}m — {samAlert.samId.toUpperCase()}
            </div>
          </div>
        </div>
      )}

      {/* Missile Incoming Warning — center screen flash */}
      {missileIncoming && (
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 animate-pulse">
          <div className="text-[#ff3333] text-center">
            <div className="text-lg font-bold tracking-[0.3em]">MISSILE INCOMING</div>
            <div className="text-sm mt-1">
              {Math.round(missileIncoming.distance)}m — {missileIncoming.timeToImpact.toFixed(1)}s
            </div>
            <div className="text-[10px] text-[#ff6666] mt-2 tracking-wider">
              Z = CHAFF // X = FLARES
            </div>
          </div>
        </div>
      )}

      {/* Missile Defeated */}
      {lastDefeated && (
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2">
          <div className="text-[#00ff66] text-center text-sm tracking-[0.2em]">
            MISSILE DEFEATED ({lastDefeated.method.toUpperCase()})
          </div>
        </div>
      )}

      {/* Munitions panel — bottom left, above footer */}
      <div className="absolute bottom-20 left-4">
        <div className="text-[10px] text-[#4a6a8a] tracking-wider mb-2">MUNITIONS</div>
        <div className="space-y-2">
          {/* Countermeasures */}
          <div className="flex gap-3">
            {/* Bomb — same width as the two below */}
            <div className="flex-1 px-3 py-1.5 border border-[#ff3333]/30 rounded-sm text-[#ff3333] bg-[#1a0a0a]/60 text-center" style={{ gridColumn: 'span 2' }}>
              <span className="text-[10px] tracking-wider">SPACE </span>
              <span className="text-sm font-bold">JDAM</span>
            </div>
          </div>
          <div className="flex gap-3">
            <div className={`px-3 py-1 border rounded-sm ${
              chaff > 0 ? 'border-[#00e5ff]/30 text-[#00e5ff]' : 'border-[#333]/30 text-[#333]'
            }`}>
              <span className="text-[10px] tracking-wider">Z CHAFF </span>
              <span className="text-sm font-bold">{chaff}</span>
            </div>
            <div className={`px-3 py-1 border rounded-sm ${
              flares > 0 ? 'border-[#ffc107]/30 text-[#ffc107]' : 'border-[#333]/30 text-[#333]'
            }`}>
              <span className="text-[10px] tracking-wider">X FLARE </span>
              <span className="text-sm font-bold">{flares}</span>
            </div>
          </div>
        </div>
        {missilesEvaded > 0 && (
          <div className="text-[10px] text-[#00ff66] mt-2 tracking-wider">
            MISSILES EVADED: {missilesEvaded}
          </div>
        )}
      </div>
    </div>
  );
}
