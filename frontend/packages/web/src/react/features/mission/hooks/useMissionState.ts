import { useState, useEffect, useCallback, useRef } from 'react';
import { useGameEvent } from '../../../hooks/useGameEvent';
import { useGameMethod } from '../../../hooks/useGameMethod';
import { getTokens } from '../../../../utils/tokenValidator';
import type { Detection } from '../../detection/hooks/useObjectDetection';

const MAPBOX_TOKEN = getTokens().mapbox;

export interface WaypointLog {
  index: number;
  lat: number;
  lon: number;
  alt: number;
  detections: Detection[];
  scanned: boolean;
  scanning: boolean;
}

export interface ScanLog {
  lat: number;
  lon: number;
  alt: number;
  detections: Detection[];
  timestamp: number;
}

export interface UniqueObject {
  class: string;
  lat: number;
  lon: number;
}

export interface MissionState {
  isActive: boolean;        // planned mission auto-fly in progress
  isComplete: boolean;      // mission/report ready to view
  isTracking: boolean;      // free flight ISR tracking
  currentWaypointIndex: number;
  waypoints: WaypointLog[]; // only for planned missions
  scanLogs: ScanLog[];      // free flight ISR scans
  totalDetections: number;  // raw count
  uniqueObjects: UniqueObject[]; // deduplicated
  startTime: number | null;
  analysis: AnalysisResult | null;
  isAnalyzing: boolean;
}

// Convert a detection's bbox center (in image pixels) to approximate world lat/lon
// given the scan's center lat/lon and zoom level
function detectionToWorldPos(
  det: Detection,
  scanLat: number,
  scanLon: number,
  scanAlt: number
): { lat: number; lon: number } {
  const imgSize = 600;
  const zoom = scanAlt <= 200 ? 19 : scanAlt <= 400 ? 18 : scanAlt <= 800 ? 18 : scanAlt <= 1500 ? 17 : 16;
  // Meters per pixel at this zoom level (approximate)
  const metersPerPixel = (156543.03 * Math.cos(scanLat * Math.PI / 180)) / Math.pow(2, zoom);
  const cx = ((det.bbox.x1 + det.bbox.x2) / 2 - imgSize / 2) * metersPerPixel;
  const cy = ((det.bbox.y1 + det.bbox.y2) / 2 - imgSize / 2) * metersPerPixel;
  const lat = scanLat - cy / 111320;
  const lon = scanLon + cx / (111320 * Math.cos(scanLat * Math.PI / 180));
  return { lat, lon };
}

// Check if a detection already exists in uniqueObjects (same class within ~30m)
function isDuplicate(obj: { class: string; lat: number; lon: number }, existing: UniqueObject[]): boolean {
  const threshold = 0.0003; // ~30m in degrees
  return existing.some(e =>
    e.class === obj.class &&
    Math.abs(e.lat - obj.lat) < threshold &&
    Math.abs(e.lon - obj.lon) < threshold
  );
}

function deduplicateDetections(
  scanLogs: ScanLog[],
  waypoints: WaypointLog[]
): UniqueObject[] {
  const unique: UniqueObject[] = [];

  const allScans = [
    ...scanLogs.map(s => ({ lat: s.lat, lon: s.lon, alt: s.alt, detections: s.detections })),
    ...waypoints.filter(w => w.scanned).map(w => ({ lat: w.lat, lon: w.lon, alt: w.alt, detections: w.detections })),
  ];

  for (const scan of allScans) {
    for (const det of scan.detections) {
      const worldPos = detectionToWorldPos(det, scan.lat, scan.lon, scan.alt);
      const obj = { class: det.class, lat: worldPos.lat, lon: worldPos.lon };
      if (!isDuplicate(obj, unique)) {
        unique.push(obj);
      }
    }
  }

  return unique;
}

export interface AnalysisResult {
  summary: string;
  threat_level: 'low' | 'medium' | 'high';
  recommendations: string[];
}

async function fetchISRDetections(lat: number, lon: number, alt: number): Promise<Detection[]> {
  try {
    const zoom = alt <= 200 ? 18 : alt <= 500 ? 17 : alt <= 1000 ? 16 : 15;
    const satUrl = `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/${lon},${lat},${zoom},0/600x600?access_token=${MAPBOX_TOKEN}`;
    const imgRes = await fetch(satUrl);
    const blob = await imgRes.blob();

    const formData = new FormData();
    formData.append('image', blob, 'scan.jpg');

    const detectRes = await fetch('/api/detect', { method: 'POST', body: formData });
    const result = await detectRes.json();
    return result.detections || [];
  } catch {
    return [];
  }
}

export function useMissionState() {
  const [state, setState] = useState<MissionState>({
    isActive: false,
    isComplete: false,
    isTracking: true,
    currentWaypointIndex: 0,
    waypoints: [],
    scanLogs: [],
    totalDetections: 0,
    uniqueObjects: [],
    startTime: Date.now(),
    analysis: null,
    isAnalyzing: false,
  });

  const stateRef = useRef(state);
  stateRef.current = state;

  const waypointReached = useGameEvent('waypointReached');
  const missionComplete = useGameEvent('missionComplete');
  const missionAborted = useGameEvent('missionAborted');
  const { getWaypointPositions, startMission, abortMission, clearWaypoints } = useGameMethod();

  // Receive detections from the bottom-right ISR panel
  const addISRDetections = useCallback((detections: Detection[], lat: number, lon: number, alt: number) => {
    if (!stateRef.current.isTracking || stateRef.current.isActive) return;

    setState(prev => {
      const newScan: ScanLog = { lat, lon, alt, detections, timestamp: Date.now() };
      const logs = [...prev.scanLogs, newScan];
      const total = logs.reduce((acc, s) => acc + s.detections.length, 0);
      const unique = deduplicateDetections(logs, prev.waypoints);
      return { ...prev, scanLogs: logs, totalDetections: total, uniqueObjects: unique };
    });
  }, []);

  // Start planned mission
  const executeMission = useCallback(() => {
    const wps = getWaypointPositions();
    if (wps.length === 0) return;

    setState({
      isActive: true,
      isComplete: false,
      isTracking: false,
      currentWaypointIndex: 0,
      waypoints: wps.map((wp, i) => ({
        index: i,
        lat: wp.lat,
        lon: wp.lon,
        alt: wp.alt,
        detections: [],
        scanned: false,
        scanning: false,
      })),
      scanLogs: [],
      totalDetections: 0,
      uniqueObjects: [],
      startTime: Date.now(),
      analysis: null,
      isAnalyzing: false,
    });

    startMission();
  }, [getWaypointPositions, startMission]);

  // Handle waypoint reached during planned mission
  useEffect(() => {
    if (!waypointReached || !stateRef.current.isActive) return;
    const idx = waypointReached.index;

    setState(prev => {
      const wps = [...prev.waypoints];
      if (wps[idx]) {
        wps[idx] = { ...wps[idx], scanning: true };
      }
      return { ...prev, currentWaypointIndex: idx + 1, waypoints: wps };
    });

    const wp = stateRef.current.waypoints[idx];
    if (wp) {
      (async () => {
        const detections = await fetchISRDetections(wp.lat, wp.lon, wp.alt);
        setState(prev => {
          const wps = [...prev.waypoints];
          if (wps[idx]) {
            wps[idx] = { ...wps[idx], detections, scanned: true, scanning: false };
          }
          const total = wps.reduce((acc, w) => acc + w.detections.length, 0);
          const unique = deduplicateDetections(prev.scanLogs, wps);
          return { ...prev, waypoints: wps, totalDetections: total, uniqueObjects: unique };
        });
      })();
    }
  }, [waypointReached]);

  // Handle planned mission complete
  useEffect(() => {
    if (!missionComplete || !stateRef.current.isActive) return;
    setState(prev => ({ ...prev, isActive: false, isComplete: true, isTracking: false }));
    runAnalysis();
  }, [missionComplete]);

  // Handle mission abort
  useEffect(() => {
    if (!missionAborted) return;
    setState(prev => ({ ...prev, isActive: false, isTracking: true }));
  }, [missionAborted]);

  const runAnalysis = async () => {
    setState(prev => ({ ...prev, isAnalyzing: true }));
    try {
      // Combine waypoints and scanLogs for analysis
      const allScans = stateRef.current.waypoints.length > 0
        ? stateRef.current.waypoints
        : stateRef.current.scanLogs.map((s, i) => ({
            index: i,
            lat: s.lat,
            lon: s.lon,
            alt: s.alt,
            detections: s.detections,
            scanned: true,
            scanning: false,
          }));

      // Reverse geocode the mission center to get location name
      let locationName = 'Unknown location';
      if (allScans.length > 0) {
        const centerLat = allScans.reduce((a, s) => a + s.lat, 0) / allScans.length;
        const centerLon = allScans.reduce((a, s) => a + s.lon, 0) / allScans.length;
        try {
          const geoRes = await fetch(
            `https://api.mapbox.com/geocoding/v5/mapbox.places/${centerLon},${centerLat}.json?access_token=${MAPBOX_TOKEN}&limit=1&types=place,locality,region`
          );
          const geoData = await geoRes.json();
          if (geoData.features && geoData.features.length > 0) {
            locationName = geoData.features[0].place_name;
          }
        } catch {}
      }

      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ waypoints: allScans, location: locationName }),
      });
      const result = await res.json();
      setState(prev => ({ ...prev, analysis: result, isAnalyzing: false }));
    } catch {
      setState(prev => ({ ...prev, isAnalyzing: false }));
    }
  };

  const handleAbort = useCallback(() => {
    abortMission();
    setState(prev => ({ ...prev, isActive: false, isTracking: true }));
  }, [abortMission]);

  const stopAndReport = useCallback(() => {
    setState(prev => ({ ...prev, isTracking: false, isComplete: true }));
    runAnalysis();
  }, []);

  const reset = useCallback(() => {
    clearWaypoints();
    setState({
      isActive: false,
      isComplete: false,
      isTracking: true,
      currentWaypointIndex: 0,
      waypoints: [],
      scanLogs: [],
      totalDetections: 0,
      uniqueObjects: [],
      startTime: Date.now(),
      analysis: null,
      isAnalyzing: false,
    });
  }, [clearWaypoints]);

  return {
    ...state,
    executeMission,
    handleAbort,
    stopAndReport,
    addISRDetections,
    reset,
  };
}
