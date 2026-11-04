import { useState, useEffect } from 'react';
import { useGameEvent } from '../../../hooks/useGameEvent';
import { getBaseLocation } from '../../../../baseLocation';
import * as Cesium from 'cesium';

export interface VehiclePosition {
  longitude: number;
  latitude: number;
  altitude: number;
  heading: number;
}

export function useVehiclePosition() {
  const vehicleState = useGameEvent('vehicleStateChanged');
  const base = getBaseLocation();
  const [position, setPosition] = useState<VehiclePosition>({
    longitude: base.longitude,
    latitude: base.latitude,
    altitude: base.altitude,
    heading: base.heading,
  });

  useEffect(() => {
    if (vehicleState?.position) {
      const cartographic = Cesium.Cartographic.fromCartesian(vehicleState.position);
      
      setPosition({
        longitude: Cesium.Math.toDegrees(cartographic.longitude),
        latitude: Cesium.Math.toDegrees(cartographic.latitude),
        altitude: cartographic.height,
        heading: Cesium.Math.toDegrees(vehicleState.heading),
      });
    }
  }, [vehicleState]);

  return position;
}

