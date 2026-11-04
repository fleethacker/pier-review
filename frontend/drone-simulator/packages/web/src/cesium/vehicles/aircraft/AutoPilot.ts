import * as Cesium from 'cesium';
import type { AircraftInput } from './AircraftPhysics';

export type AutoPilotCallback = (event: 'waypointReached' | 'missionComplete', index: number) => void;

export type FlightProfile = 'noe' | 'safe' | 'speed' | 'stealth' | 'recon';

interface FlightProfileConfig {
  name: string;
  description: string;
  cruiseSpeed: number;
  altitudeOffset: number; // added to waypoint altitude: negative = below, 0 = exact, positive = above
  waypointThreshold: number;
  preferLowAltitude: boolean;
  maxAltitude: number;
}

const FLIGHT_PROFILES: Record<FlightProfile, FlightProfileConfig> = {
  noe: {
    name: 'NOE (Nap of Earth)',
    description: 'Terrain-hugging flight to avoid radar detection. Maximum risk, minimum signature.',
    cruiseSpeed: 150,
    altitudeOffset: -50, // fly 50m below waypoint altitude (closer to terrain)
    waypointThreshold: 100,
    preferLowAltitude: true,
    maxAltitude: 100,
  },
  stealth: {
    name: 'STEALTH',
    description: 'Low and slow approach. Reduced speed minimizes acoustic and visual signature.',
    cruiseSpeed: 80,
    altitudeOffset: -30,
    waypointThreshold: 80,
    preferLowAltitude: true,
    maxAltitude: 200,
  },
  recon: {
    name: 'RECON',
    description: 'Standard ISR altitude for optimal camera coverage. Balanced speed and scanning.',
    cruiseSpeed: 180,
    altitudeOffset: 0,
    waypointThreshold: 80,
    preferLowAltitude: false,
    maxAltitude: 2000,
  },
  safe: {
    name: 'HIGH ALTITUDE',
    description: 'Maximum altitude for drone safety. Minimizes collision risk and threat exposure.',
    cruiseSpeed: 200,
    altitudeOffset: 200, // fly 200m above waypoint altitude
    waypointThreshold: 100,
    preferLowAltitude: false,
    maxAltitude: 5000,
  },
  speed: {
    name: 'FAST TRANSIT',
    description: 'Maximum speed between waypoints. Minimizes time on station, maximum area coverage.',
    cruiseSpeed: 600,
    altitudeOffset: 100,
    waypointThreshold: 150, // larger threshold at high speed
    preferLowAltitude: false,
    maxAltitude: 3000,
  },
};

export function getFlightProfiles(): { id: FlightProfile; name: string; description: string }[] {
  return Object.entries(FLIGHT_PROFILES).map(([id, config]) => ({
    id: id as FlightProfile,
    name: config.name,
    description: config.description,
  }));
}

export class AutoPilot {
  private waypoints: Cesium.Cartesian3[] = [];
  private currentIndex: number = 0;
  private active: boolean = false;
  private callback: AutoPilotCallback | null = null;
  private profile: FlightProfileConfig = FLIGHT_PROFILES.recon;
  private currentProfile: FlightProfile = 'recon';
  private turnCooldown: number = 0;
  private altCooldown: number = 0;

  public setFlightProfile(profile: FlightProfile): void {
    this.profile = FLIGHT_PROFILES[profile];
    this.currentProfile = profile;
  }

  public getFlightProfile(): FlightProfile {
    return this.currentProfile;
  }

  public start(waypoints: Cesium.Cartesian3[], callback: AutoPilotCallback): void {
    if (waypoints.length === 0) return;
    this.waypoints = waypoints;
    this.currentIndex = 0;
    this.active = true;
    this.callback = callback;
    console.log(`AutoPilot: Mission started [${this.profile.name}] with ${waypoints.length} waypoints`);
  }

  public stop(): void {
    this.active = false;
    this.waypoints = [];
    this.currentIndex = 0;
    this.callback = null;
  }

  public isActive(): boolean {
    return this.active;
  }

  public getCurrentWaypointIndex(): number {
    return this.currentIndex;
  }

  public computeInput(currentPosition: Cesium.Cartesian3, currentHeading: number): AircraftInput {
    if (!this.active || this.currentIndex >= this.waypoints.length) {
      return this.neutralInput();
    }

    const target = this.waypoints[this.currentIndex];
    const distance = Cesium.Cartesian3.distance(currentPosition, target);

    if (distance < this.profile.waypointThreshold) {
      this.callback?.('waypointReached', this.currentIndex);
      this.currentIndex++;

      if (this.currentIndex >= this.waypoints.length) {
        this.callback?.('missionComplete', this.currentIndex);
        this.active = false;
        return this.neutralInput();
      }
    }

    const actualTarget = this.waypoints[Math.min(this.currentIndex, this.waypoints.length - 1)];
    return this.computeSteeringInput(currentPosition, currentHeading, actualTarget);
  }

  private computeSteeringInput(
    currentPosition: Cesium.Cartesian3,
    currentHeading: number,
    target: Cesium.Cartesian3
  ): AircraftInput {
    const currentCart = Cesium.Cartographic.fromCartesian(currentPosition);
    const targetCart = Cesium.Cartographic.fromCartesian(target);

    // Bearing to target
    const dLon = targetCart.longitude - currentCart.longitude;
    const y = Math.sin(dLon) * Math.cos(targetCart.latitude);
    const x = Math.cos(currentCart.latitude) * Math.sin(targetCart.latitude) -
              Math.sin(currentCart.latitude) * Math.cos(targetCart.latitude) * Math.cos(dLon);
    let bearing = Math.atan2(y, x);
    if (bearing < 0) bearing += Cesium.Math.TWO_PI;

    // Heading error
    let headingError = bearing - currentHeading;
    while (headingError > Math.PI) headingError -= Cesium.Math.TWO_PI;
    while (headingError < -Math.PI) headingError += Cesium.Math.TWO_PI;

    const absError = Math.abs(headingError);
    let turnLeft = false;
    let turnRight = false;

    // Cooldown prevents rapid turn toggling — apply a short turn pulse then wait
    if (this.turnCooldown > 0) {
      this.turnCooldown--;
    } else if (absError > Cesium.Math.toRadians(15)) {
      // Large error: turn for 8 frames then coast for 15
      turnLeft = headingError < 0;
      turnRight = headingError > 0;
      this.turnCooldown = 15;
    } else if (absError > Cesium.Math.toRadians(5)) {
      // Small error: brief tap for 3 frames then coast for 20
      turnLeft = headingError < 0;
      turnRight = headingError > 0;
      this.turnCooldown = 20;
    }
    // Under 5 degrees: fly straight, let it drift naturally

    // Altitude control with profile offset
    let targetAlt = targetCart.height + this.profile.altitudeOffset;
    if (this.profile.preferLowAltitude) {
      targetAlt = Math.min(targetAlt, this.profile.maxAltitude);
    }
    targetAlt = Math.max(targetAlt, 20);

    const altError = targetAlt - currentCart.height;
    let altitudeUp = false;
    let altitudeDown = false;

    if (this.altCooldown > 0) {
      this.altCooldown--;
    } else if (Math.abs(altError) > 30) {
      altitudeUp = altError > 0;
      altitudeDown = altError < 0;
      this.altCooldown = 10;
    }

    return {
      throttle: true,
      brake: false,
      turnLeft,
      turnRight,
      altitudeUp,
      altitudeDown,
      rollLeft: false,
      rollRight: false,
      targetSpeed: this.profile.cruiseSpeed,
    };
  }

  private neutralInput(): AircraftInput {
    return {
      throttle: false,
      brake: false,
      turnLeft: false,
      turnRight: false,
      altitudeUp: false,
      altitudeDown: false,
      rollLeft: false,
      rollRight: false,
    };
  }
}
