import { useState, useCallback, useEffect, useRef } from 'react';
import { useGameBridge } from '../../../hooks/useGameBridge';
import type {
  MaverickPhase,
  MaverickPhaseChangedData,
  SAMAlertData,
  MissileIncomingData,
  MissileDefeatedData,
  CountermeasureDeployedData,
  MaverickCompleteData,
  MaverickFailedData,
  MaverickStateData,
} from '../../../../cesium/bridge/types';

export interface MaverickState {
  phase: MaverickPhase;
  missionTime: number;
  chaff: number;
  flares: number;
  missilesEvaded: number;
  agl: number;
  altitudeWarning: boolean;

  // Threat alerts
  samAlert: SAMAlertData | null;
  missileIncoming: MissileIncomingData | null;
  lastDefeated: MissileDefeatedData | null;
  lastCountermeasure: CountermeasureDeployedData | null;

  // Completion
  completeData: MaverickCompleteData | null;
  failedData: MaverickFailedData | null;

  // Actions
  retry: () => void;
}

export function useMaverickState(): MaverickState {
  const bridge = useGameBridge();
  const [phase, setPhase] = useState<MaverickPhase>('cinematic');
  const [missionTime, setMissionTime] = useState(0);
  const [chaff, setChaff] = useState(8);
  const [flares, setFlares] = useState(8);
  const [missilesEvaded, setMissilesEvaded] = useState(0);
  const [agl, setAgl] = useState(500);
  const [altitudeWarning, setAltitudeWarning] = useState(false);
  const [samAlert, setSamAlert] = useState<SAMAlertData | null>(null);
  const [missileIncoming, setMissileIncoming] = useState<MissileIncomingData | null>(null);
  const [lastDefeated, setLastDefeated] = useState<MissileDefeatedData | null>(null);
  const [lastCountermeasure, setLastCountermeasure] = useState<CountermeasureDeployedData | null>(null);
  const [completeData, setCompleteData] = useState<MaverickCompleteData | null>(null);
  const [failedData, setFailedData] = useState<MaverickFailedData | null>(null);

  const samAlertTimeout = useRef<ReturnType<typeof setTimeout>>();
  const missileTimeout = useRef<ReturnType<typeof setTimeout>>();
  const defeatedTimeout = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    const handlePhase = (data: MaverickPhaseChangedData) => setPhase(data.phase);
    const handleState = (data: MaverickStateData) => {
      setPhase(data.phase);
      setMissionTime(data.missionTime);
      setChaff(data.chaff);
      setFlares(data.flares);
      setMissilesEvaded(data.missilesEvaded);
      setAgl(data.agl);
      setAltitudeWarning(data.altitudeWarning);
    };
    const handleSamAlert = (data: SAMAlertData) => {
      setSamAlert(data);
      if (samAlertTimeout.current) clearTimeout(samAlertTimeout.current);
      samAlertTimeout.current = setTimeout(() => setSamAlert(null), 2000);
    };
    const handleMissile = (data: MissileIncomingData) => {
      setMissileIncoming(data);
      if (missileTimeout.current) clearTimeout(missileTimeout.current);
      missileTimeout.current = setTimeout(() => setMissileIncoming(null), 3000);
    };
    const handleDefeated = (data: MissileDefeatedData) => {
      setLastDefeated(data);
      if (defeatedTimeout.current) clearTimeout(defeatedTimeout.current);
      defeatedTimeout.current = setTimeout(() => setLastDefeated(null), 2000);
    };
    const handleCM = (data: CountermeasureDeployedData) => setLastCountermeasure(data);
    const handleComplete = (data: MaverickCompleteData) => setCompleteData(data);
    const handleFailed = (data: MaverickFailedData) => setFailedData(data);

    bridge.on('maverickPhaseChanged', handlePhase);
    bridge.on('maverickState', handleState);
    bridge.on('samAlert', handleSamAlert);
    bridge.on('missileIncoming', handleMissile);
    bridge.on('missileDefeated', handleDefeated);
    bridge.on('countermeasureDeployed', handleCM);
    bridge.on('maverickComplete', handleComplete);
    bridge.on('maverickFailed', handleFailed);

    return () => {
      bridge.off('maverickPhaseChanged', handlePhase);
      bridge.off('maverickState', handleState);
      bridge.off('samAlert', handleSamAlert);
      bridge.off('missileIncoming', handleMissile);
      bridge.off('missileDefeated', handleDefeated);
      bridge.off('countermeasureDeployed', handleCM);
      bridge.off('maverickComplete', handleComplete);
      bridge.off('maverickFailed', handleFailed);
      if (samAlertTimeout.current) clearTimeout(samAlertTimeout.current);
      if (missileTimeout.current) clearTimeout(missileTimeout.current);
      if (defeatedTimeout.current) clearTimeout(defeatedTimeout.current);
    };
  }, [bridge]);

  const retry = useCallback(() => {
    bridge.retryMaverickMission();
    setPhase('cinematic');
    setCompleteData(null);
    setFailedData(null);
    setMissilesEvaded(0);
    setChaff(8);
    setFlares(8);
  }, [bridge]);

  return {
    phase,
    missionTime,
    chaff,
    flares,
    missilesEvaded,
    agl,
    altitudeWarning,
    samAlert,
    missileIncoming,
    lastDefeated,
    lastCountermeasure,
    completeData,
    failedData,
    retry,
  };
}
