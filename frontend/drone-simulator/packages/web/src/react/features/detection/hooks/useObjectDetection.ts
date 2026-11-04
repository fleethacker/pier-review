import { useState, useRef, useCallback, useEffect } from 'react';
import { getTokens } from '../../../../utils/tokenValidator';

export interface Detection {
  class: string;
  confidence: number;
  bbox: { x1: number; y1: number; x2: number; y2: number };
  id: string;
}

export interface DetectionResult {
  detections: Detection[];
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  isLoading: boolean;
  error: string | null;
  lastUpdated: number;
  triggerDetection: () => void;
}

interface UseObjectDetectionOptions {
  latitude: number;
  longitude: number;
  altitude: number;
  heading: number;
  speed: number;
  getAGL: () => number;
  isActive: boolean;
}

interface RawDetection {
  class: string;
  confidence: number;
  bbox: { x1: number; y1: number; x2: number; y2: number };
}

const MAPBOX_TOKEN = getTokens().mapbox;
const POLL_INTERVAL_MS = 1500;

// Predict where drone will be ~2 seconds from now based on current speed/heading
// This compensates for the fetch + detection latency
function predictPosition(
  lat: number, lon: number, headingDeg: number, speedKmh: number
): [number, number] {
  const lookAheadSeconds = 2;
  const speedMs = (speedKmh / 3.6);
  const offsetMeters = speedMs * lookAheadSeconds;
  if (offsetMeters < 5) return [lon, lat]; // barely moving, no offset
  const headingRad = (headingDeg * Math.PI) / 180;
  const dLat = (offsetMeters / 111320) * Math.cos(headingRad);
  const dLon = (offsetMeters / (111320 * Math.cos((lat * Math.PI) / 180))) * Math.sin(headingRad);
  return [lon + dLon, lat + dLat];
}

// Map AGL (height above ground) to Mapbox zoom level
function aglToZoom(agl: number): number {
  const clamped = Math.max(20, Math.min(5000, agl));
  const zoom = 26 - Math.log2(clamped);
  return Math.round(Math.max(12, Math.min(20, zoom)));
}

// Match new detections to previous ones by class + proximity for stable IDs
function matchDetections(
  prev: Detection[],
  raw: RawDetection[]
): Detection[] {
  const used = new Set<number>();
  const result: Detection[] = [];

  for (const r of raw) {
    const cx = (r.bbox.x1 + r.bbox.x2) / 2;
    const cy = (r.bbox.y1 + r.bbox.y2) / 2;

    let bestIdx = -1;
    let bestDist = Infinity;

    for (let i = 0; i < prev.length; i++) {
      if (used.has(i) || prev[i].class !== r.class) continue;
      const pcx = (prev[i].bbox.x1 + prev[i].bbox.x2) / 2;
      const pcy = (prev[i].bbox.y1 + prev[i].bbox.y2) / 2;
      const dist = Math.sqrt((cx - pcx) ** 2 + (cy - pcy) ** 2);
      if (dist < bestDist && dist < 150) {
        bestDist = dist;
        bestIdx = i;
      }
    }

    if (bestIdx >= 0) {
      used.add(bestIdx);
      result.push({ ...r, id: prev[bestIdx].id });
    } else {
      result.push({ ...r, id: `${r.class}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}` });
    }
  }

  return result;
}

export function useObjectDetection({
  latitude,
  longitude,
  altitude,
  heading,
  speed,
  getAGL,
  isActive,
}: UseObjectDetectionOptions): DetectionResult {
  const [detections, setDetections] = useState<Detection[]>([]);
  const [imageUrl, setImageUrl] = useState('');
  const [imageWidth, setImageWidth] = useState(0);
  const [imageHeight, setImageHeight] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState(0);

  const isLoadingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const latRef = useRef(latitude);
  const lonRef = useRef(longitude);
  const altRef = useRef(altitude);
  const hdgRef = useRef(heading);
  const spdRef = useRef(speed);
  const detectionsRef = useRef<Detection[]>([]);

  // Update refs every render so the callback always reads fresh values
  latRef.current = latitude;
  lonRef.current = longitude;
  altRef.current = altitude;
  hdgRef.current = heading;
  spdRef.current = speed;

  const runDetection = useCallback(async () => {
    if (isLoadingRef.current) return;
    isLoadingRef.current = true;
    setIsLoading(true);
    setError(null);

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const lat = latRef.current;
    const lon = lonRef.current;
    const alt = altRef.current;
    const hdg = hdgRef.current;
    const spd = spdRef.current;
    const agl = getAGL();
    const zoom = aglToZoom(agl);
    console.log(`ISR: agl=${Math.round(agl)} zoom=${zoom}`);
    const bearing = (Math.round(hdg) + 90) % 360;
    const [predLon, predLat] = predictPosition(lat, lon, hdg, spd);

    try {
      const satUrl = `https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/${predLon},${predLat},${zoom},${bearing}/1024x1024?access_token=${MAPBOX_TOKEN}`;
      const response = await fetch(satUrl, { signal: controller.signal });
      if (!response.ok) throw new Error(`Satellite image fetch failed: ${response.status}`);
      const imageBlob = await response.blob();
      const displayUrl = satUrl;

      const formData = new FormData();
      formData.append('image', imageBlob, 'capture.jpg');

      const detectResponse = await fetch('/api/detect', {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });

      if (!detectResponse.ok) {
        throw new Error(`Detection failed: ${detectResponse.status}`);
      }

      const result = await detectResponse.json();

      const matched = matchDetections(detectionsRef.current, result.detections);
      detectionsRef.current = matched;

      setDetections(matched);
      setImageUrl(displayUrl);
      setImageWidth(result.image_width);
      setImageHeight(result.image_height);
      setLastUpdated(Date.now());
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Detection failed');
      }
    } finally {
      isLoadingRef.current = false;
      setIsLoading(false);
    }
  }, []);

  // Poll while active
  useEffect(() => {
    if (!isActive) return;

    runDetection();

    const interval = setInterval(() => {
      runDetection();
    }, POLL_INTERVAL_MS);

    return () => {
      clearInterval(interval);
      abortControllerRef.current?.abort();
    };
  }, [isActive, runDetection]);

  return {
    detections,
    imageUrl,
    imageWidth,
    imageHeight,
    isLoading,
    error,
    lastUpdated,
    triggerDetection: runDetection,
  };
}
