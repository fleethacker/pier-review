import { useState, useRef, useEffect } from 'react';
import { useVehiclePosition } from '../../minimap/hooks/useVehiclePosition';

interface PathPoint {
  lat: number;
  lon: number;
  alt: number;
  timestamp: number;
}

const MAX_POINTS = 5000;
const SAMPLE_INTERVAL_MS = 1000;

export function useFlightPath() {
  const position = useVehiclePosition();
  const [path, setPath] = useState<PathPoint[]>([]);
  const lastSampleTime = useRef(0);
  const startTime = useRef(Date.now());

  useEffect(() => {
    const now = Date.now();
    if (now - lastSampleTime.current < SAMPLE_INTERVAL_MS) return;
    if (position.latitude === 0 && position.longitude === 0) return;

    lastSampleTime.current = now;

    setPath((prev) => {
      const point: PathPoint = {
        lat: position.latitude,
        lon: position.longitude,
        alt: position.altitude,
        timestamp: now,
      };

      const next = [...prev, point];
      if (next.length > MAX_POINTS) next.shift();
      return next;
    });
  }, [position.latitude, position.longitude, position.altitude]);

  const clearPath = () => {
    setPath([]);
    startTime.current = Date.now();
  };

  // Calculate total distance in km
  const totalDistance = path.reduce((acc, point, i) => {
    if (i === 0) return 0;
    const prev = path[i - 1];
    const dLat = (point.lat - prev.lat) * 111.32;
    const dLon = (point.lon - prev.lon) * 111.32 * Math.cos((point.lat * Math.PI) / 180);
    return acc + Math.sqrt(dLat * dLat + dLon * dLon);
  }, 0);

  const flightDuration = path.length > 0
    ? Math.floor((Date.now() - startTime.current) / 1000)
    : 0;

  return {
    path,
    clearPath,
    totalDistance,
    flightDuration,
    currentPosition: position,
  };
}
