import { useMaverickState } from '../features/maverick/hooks/useMaverickState';
import { MaverickHUD } from '../features/maverick/components/MaverickHUD';
import { MaverickBriefing } from '../features/maverick/components/MaverickBriefing';
import { MaverickComplete } from '../features/maverick/components/MaverickComplete';
import { MaverickFailed } from '../features/maverick/components/MaverickFailed';
import { BombTargeting } from '../features/maverick/components/BombTargeting';
import { useState, useEffect } from 'react';
import { useGameBridge } from '../hooks/useGameBridge';

export function MaverickModeUI() {
  const state = useMaverickState();
  const bridge = useGameBridge();
  const [bombState, setBombState] = useState({
    isTargetLocked: false,
    bombDropped: false,
    bombHit: false,
    distanceToTarget: 9999,
    noLockAttempt: false,
  });

  // Listen for bomb events
  useEffect(() => {
    const unsubLock = bridge.on('bombLock', (data) => {
      setBombState(prev => ({
        ...prev,
        isTargetLocked: data.locked,
        distanceToTarget: data.distance,
        noLockAttempt: data.noLockAttempt || false,
      }));
    });
    const unsubDrop = bridge.on('bombDropped', () => {
      setBombState(prev => ({ ...prev, bombDropped: true }));
    });
    const unsubHit = bridge.on('bombHit', () => {
      setBombState(prev => ({ ...prev, bombHit: true }));
    });

    return () => {
      unsubLock();
      unsubDrop();
      unsubHit();
    };
  }, [bridge]);

  // Reset bomb state on phase change
  useEffect(() => {
    if (state.phase === 'canyon_run') {
      setBombState({
        isTargetLocked: false,
        bombDropped: false,
        bombHit: false,
        distanceToTarget: 9999,
      });
    }
  }, [state.phase]);

  return (
    <>
      {/* Always show HUD during mission */}
      <MaverickHUD state={state} />

      {/* Briefing screen — dismisses itself on button click */}
      <MaverickBriefing />

      {/* Bomb targeting system */}
      <BombTargeting
        phase={state.phase}
        isTargetLocked={bombState.isTargetLocked}
        bombDropped={bombState.bombDropped}
        bombHit={bombState.bombHit}
        distanceToTarget={bombState.distanceToTarget}
        noLockAttempt={bombState.noLockAttempt}
      />

      {/* Mission complete */}
      {state.completeData && (
        <MaverickComplete data={state.completeData} onRetry={state.retry} />
      )}

      {/* Mission failed */}
      {state.failedData && (
        <MaverickFailed data={state.failedData} onRetry={state.retry} />
      )}
    </>
  );
}
