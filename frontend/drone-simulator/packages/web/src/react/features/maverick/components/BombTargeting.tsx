import { useState, useEffect } from 'react';
import { BOMB_TARGET } from '../../../../cesium/missions/MaverickMissionData';

interface BombTargetingProps {
  phase: string;
  isTargetLocked: boolean;
  bombDropped: boolean;
  bombHit: boolean;
  distanceToTarget: number;
  noLockAttempt: boolean;
}

export function BombTargeting({ phase, isTargetLocked, bombDropped, bombHit, distanceToTarget, noLockAttempt }: BombTargetingProps) {
  const [pulseClass, setPulseClass] = useState('');
  const [impactDismissed, setImpactDismissed] = useState(false);
  const [showNoLock, setShowNoLock] = useState(false);

  // Flash "NO LOCK" message when user tries to fire without lock
  useEffect(() => {
    if (noLockAttempt) {
      setShowNoLock(true);
      const timer = setTimeout(() => setShowNoLock(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [noLockAttempt]);
  const inFlight = phase !== 'cinematic' && phase !== 'briefing' && phase !== 'deck' && phase !== 'complete' && phase !== 'failed';
  const showTargeting = inFlight && !bombDropped && !bombHit;
  const showBombTrack = bombDropped && !bombHit;
  const showImpact = bombHit && !impactDismissed;

  // Auto-dismiss impact after 5 seconds
  useEffect(() => {
    if (bombHit && !impactDismissed) {
      const timer = setTimeout(() => setImpactDismissed(true), 5000);
      return () => clearTimeout(timer);
    }
  }, [bombHit, impactDismissed]);

  useEffect(() => {
    if (isTargetLocked) {
      setPulseClass('animate-pulse');
    } else {
      setPulseClass('');
    }
  }, [isTargetLocked]);

  if (!showTargeting && !showBombTrack && !showImpact && !showNoLock) return null;

  return (
    <div className="fixed inset-0 pointer-events-none z-40 font-mono flex items-center justify-center">
      {/* Targeting reticle overlay */}
      {showTargeting && (
        <div className="relative">
          {/* Outer targeting diamond */}
          <svg width="200" height="200" viewBox="0 0 200 200" className={pulseClass}>
            {/* Outer diamond */}
            <polygon
              points="100,10 190,100 100,190 10,100"
              fill="none"
              stroke={isTargetLocked ? '#ff3333' : '#00e5ff'}
              strokeWidth="1.5"
              opacity={isTargetLocked ? 1 : 0.5}
            />
            {/* Inner crosshairs */}
            <line x1="100" y1="60" x2="100" y2="85" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" />
            <line x1="100" y1="115" x2="100" y2="140" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" />
            <line x1="60" y1="100" x2="85" y2="100" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" />
            <line x1="115" y1="100" x2="140" y2="100" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" />
            {/* Center dot */}
            <circle cx="100" cy="100" r="3" fill={isTargetLocked ? '#ff3333' : '#00e5ff'} opacity="0.8" />
            {/* Corner brackets */}
            <path d="M30,30 L30,50" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M30,30 L50,30" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M170,30 L170,50" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M170,30 L150,30" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M30,170 L30,150" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M30,170 L50,170" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M170,170 L170,150" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />
            <path d="M170,170 L150,170" stroke={isTargetLocked ? '#ff3333' : '#00e5ff'} strokeWidth="1" opacity="0.4" />

            {/* X marker when locked */}
            {isTargetLocked && (
              <>
                <line x1="85" y1="85" x2="115" y2="115" stroke="#ff3333" strokeWidth="2.5" />
                <line x1="115" y1="85" x2="85" y2="115" stroke="#ff3333" strokeWidth="2.5" />
              </>
            )}
          </svg>

          {/* Distance readout */}
          <div className="absolute -bottom-8 left-1/2 -translate-x-1/2 text-center whitespace-nowrap">
            <div className={`text-xs tracking-wider ${isTargetLocked ? 'text-[#ff3333]' : 'text-[#00e5ff]'}`}>
              TGT {Math.round(distanceToTarget)}m
            </div>
          </div>

          {/* Lock status */}
          <div className="absolute -top-8 left-1/2 -translate-x-1/2 text-center whitespace-nowrap">
            <div className={`text-[10px] tracking-[0.3em] ${
              isTargetLocked ? 'text-[#ff3333] animate-pulse' : 'text-[#00e5ff]/50'
            }`}>
              {isTargetLocked ? 'TARGET LOCKED — PRESS SPACE TO DROP' : 'ACQUIRING TARGET...'}
            </div>
          </div>
        </div>
      )}

      {/* Bomb in flight */}
      {showBombTrack && (
        <div className="relative">
          <svg width="120" height="120" viewBox="0 0 120 120">
            {/* Tracking circle */}
            <circle cx="60" cy="60" r="40" fill="none" stroke="#ffc107" strokeWidth="1" strokeDasharray="4,4">
              <animateTransform attributeName="transform" type="rotate" from="0 60 60" to="360 60 60" dur="2s" repeatCount="indefinite" />
            </circle>
            <circle cx="60" cy="60" r="4" fill="#ffc107" />
          </svg>
          <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 text-[#ffc107] text-xs tracking-wider">
            BOMB IN FLIGHT
          </div>
        </div>
      )}

      {/* NO LOCK warning when user tries to fire too far */}
      {showNoLock && (
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2">
          <div className="px-6 py-3 bg-[#ff3333]/30 border-2 border-[#ff3333] rounded-sm animate-pulse">
            <div className="text-[#ff3333] text-sm font-mono font-bold tracking-[0.3em]">
              NO LOCK — GET WITHIN {(BOMB_TARGET?.lockDistance || 1500)}m OF TARGET
            </div>
            <div className="text-[#ff6666] text-xs font-mono mt-1 text-center">
              TARGET DISTANCE: {Math.round(distanceToTarget)}m
            </div>
          </div>
        </div>
      )}

      {/* Impact confirmation */}
      {showImpact && (
        <div className="relative">
          <svg width="200" height="200" viewBox="0 0 200 200">
            {/* Impact burst */}
            <circle cx="100" cy="100" r="50" fill="none" stroke="#ff6600" strokeWidth="3" opacity="0.8">
              <animate attributeName="r" from="20" to="70" dur="1s" repeatCount="indefinite" />
              <animate attributeName="opacity" from="1" to="0" dur="1s" repeatCount="indefinite" />
            </circle>
            <circle cx="100" cy="100" r="30" fill="none" stroke="#ff3300" strokeWidth="2" opacity="0.8">
              <animate attributeName="r" from="10" to="50" dur="0.8s" repeatCount="indefinite" />
              <animate attributeName="opacity" from="1" to="0" dur="0.8s" repeatCount="indefinite" />
            </circle>
            {/* Center X */}
            <line x1="85" y1="85" x2="115" y2="115" stroke="#ff3300" strokeWidth="3" />
            <line x1="115" y1="85" x2="85" y2="115" stroke="#ff3300" strokeWidth="3" />
          </svg>
          <div className="absolute -bottom-6 left-1/2 -translate-x-1/2 text-[#ff6600] text-sm font-bold tracking-[0.3em]">
            TARGET DESTROYED
          </div>
        </div>
      )}
    </div>
  );
}
