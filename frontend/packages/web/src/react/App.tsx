import { IntroScreen } from './shared/components/IntroScreen';
import { DebugPanel } from './features/debug/components/DebugPanel';
import { PlayModeUI } from './layouts/PlayModeUI';
import { BuilderModeUI } from './layouts/BuilderModeUI';
import { MaverickModeUI } from './layouts/MaverickModeUI';
import { StatusBar } from './features/hud/components/StatusBar';
import { Reticle } from './features/hud/components/Reticle';
import { ModeToggle } from './features/builder/components/ModeToggle';
import { useGameMode } from './hooks/useGameMode';
import { ThrottleSlider } from './features/controls/components/mobile/ThrottleSlider';
import { isMobileDevice } from './shared/utils/mobileDetect';
import { useGameMethod } from './hooks/useGameMethod';
import { HUD } from './features/hud/components/HUD';
import { CrashScreen } from './features/crash/components/CrashScreen';
import { useMissionState } from './features/mission/hooks/useMissionState';
import { MissionStatusPanel } from './features/mission/components/MissionStatusPanel';
import { MissionSummaryPanel } from './features/mission/components/MissionSummaryPanel';
import { MissionTracker } from './features/mission/components/MissionTracker';
import { WindTunnelPage } from './features/windtunnel/components/WindTunnelPage';
import { useState } from 'react';

export function App() {
  const { mode } = useGameMode();
  const isMobile = isMobileDevice();
  const { setThrottle } = useGameMethod();
  const mission = useMissionState();
  const [showWindTunnel, setShowWindTunnel] = useState(false);

  const handleThrottleChange = (percent: number) => {
    setThrottle(percent / 100);
  };

  return (
    <>
      {/* Global UI — skip IntroScreen in maverick mode (has its own briefing) */}
      {mode !== 'maverick' && <IntroScreen />}
      <DebugPanel />

      {/* Mode toggle — hidden in maverick mode */}
      {mode !== 'maverick' && (
        <div className="fixed bottom-[72px] right-[340px] md:right-[340px] z-50 pointer-events-auto">
          <ModeToggle />
        </div>
      )}

      {/* Mode-specific UI */}
      {mode === 'play' && !isMobile && <PlayModeUI onDetections={mission.addISRDetections} />}
      {mode === 'maverick' && (
        <>
          <StatusBar />
          <Reticle />
          <MaverickModeUI />
        </>
      )}
      {mode === 'builder' && <BuilderModeUI onExecuteMission={mission.executeMission} />}
      <HUD />
      {isMobile && <ThrottleSlider onChange={handleThrottleChange} />}
      <CrashScreen />

      {/* Free flight tracker (always visible during play, not during planned mission) */}
      {mission.isTracking && !mission.isActive && !mission.isComplete && mode === 'play' && (
        <MissionTracker
          scans={mission.scanLogs}
          totalDetections={mission.totalDetections}
          uniqueObjects={mission.uniqueObjects}
          startTime={mission.startTime}
          onViewReport={mission.stopAndReport}
        />
      )}

      {/* Mission status (during auto-fly) */}
      {mission.isActive && (
        <MissionStatusPanel
          currentWaypointIndex={mission.currentWaypointIndex}
          waypoints={mission.waypoints}
          totalDetections={mission.totalDetections}
          startTime={mission.startTime}
          onAbort={mission.handleAbort}
        />
      )}

      {/* Wind tunnel page */}
      {showWindTunnel && <WindTunnelPage onClose={() => setShowWindTunnel(false)} />}

      {/* Wind tunnel access button */}
      {!showWindTunnel && mode === 'play' && (
        <button
          onClick={() => setShowWindTunnel(true)}
          className="fixed top-10 left-[120px] z-50 w-10 h-10 flex items-center justify-center
                     glass-panel hover:bg-mil-border/30 transition-all duration-200
                     text-mil-dim hover:text-mil-cyan text-xs font-mono pointer-events-auto"
          title="Wind Tunnel"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M2 12h6l3-9 3 18 3-9h5" />
          </svg>
        </button>
      )}

      {/* Mission summary (after completion) */}
      {mission.isComplete && (
        <MissionSummaryPanel
          waypoints={mission.waypoints}
          totalDetections={mission.totalDetections}
          startTime={mission.startTime}
          analysis={mission.analysis}
          isAnalyzing={mission.isAnalyzing}
          onDismiss={mission.reset}
        />
      )}
    </>
  );
}
