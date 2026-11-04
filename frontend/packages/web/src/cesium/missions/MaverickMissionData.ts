/**
 * Maverick Mission Data
 *
 * Recreates the Top Gun: Maverick canyon run experience:
 * - Carrier launch off the California coast (Point Mugu)
 * - Transit to Star Wars Canyon / Rainbow Canyon (Death Valley)
 * - Low-altitude canyon run with SAM threats
 * - Egress under fire
 * - RTB to carrier
 */

export interface MissionWaypoint {
  lon: number;
  lat: number;
  alt: number; // meters MSL
  label?: string;
}

export interface SAMPosition {
  id: string;
  lon: number;
  lat: number;
  alt: number;
  detectionRadius: number; // meters
  altitudeThreshold: number; // meters AGL — above this triggers tracking
  label?: string;
  modelUrl?: string; // GLB model to use (defaults to sam-s300.glb)
}

// Aircraft carrier just offshore Ventura, CA — ~3km out in the ocean
// Short transit to Death Valley canyon for demo purposes
export const CARRIER_POSITION = {
  lon: -119.33,
  lat: 34.22,
  alt: 18, // flight deck ~18m above waterline
  heading: 315, // degrees, into the wind
};

// Carrier dimensions for spawn offset calculation
export const CARRIER_DIMENSIONS = {
  length: 330, // meters (Nimitz-class)
  width: 75,   // flight deck width
  deckHeight: 18, // meters above waterline
};

// Waypoints from carrier to canyon and back
export const MISSION_WAYPOINTS: MissionWaypoint[] = [
  // === TRANSIT PHASE: Ventura coast to canyon ===
  { lon: -118.80, lat: 34.80, alt: 1200, label: 'DEPARTURE' },
  { lon: -118.00, lat: 35.60, alt: 1500, label: 'TRANSIT' },
  { lon: -117.50, lat: 36.25, alt: 800,  label: 'DESCENT' },

  // === CANYON RUN PHASE: Through Rainbow Canyon / Star Wars Canyon ===
  // Father Crowley Vista area — canyon entrance
  { lon: -117.38, lat: 36.34, alt: 450,  label: 'CANYON-INGRESS' },
  // Into the canyon — dropping low
  { lon: -117.36, lat: 36.36, alt: 350,  label: 'CANYON-1' },
  { lon: -117.33, lat: 36.37, alt: 300,  label: 'CANYON-2' },
  // Deep in the canyon — the money run
  { lon: -117.30, lat: 36.38, alt: 280,  label: 'CANYON-3' },
  { lon: -117.27, lat: 36.39, alt: 260,  label: 'CANYON-4' },
  { lon: -117.24, lat: 36.40, alt: 270,  label: 'CANYON-5' },
  // Canyon curves
  { lon: -117.21, lat: 36.42, alt: 290,  label: 'CANYON-6' },
  { lon: -117.19, lat: 36.44, alt: 310,  label: 'CANYON-7' },
  // Target area — pull up point
  { lon: -117.17, lat: 36.46, alt: 350,  label: 'TARGET' },

  // === EGRESS PHASE: Exit canyon under heavy SAM fire ===
  { lon: -117.15, lat: 36.48, alt: 500,  label: 'EGRESS-1' },
  { lon: -117.20, lat: 36.52, alt: 800,  label: 'EGRESS-2' },
  { lon: -117.30, lat: 36.50, alt: 1000, label: 'EGRESS-3' },

  // === RTB PHASE: Return to carrier off Ventura ===
  { lon: -117.80, lat: 36.20, alt: 1200, label: 'RTB-1' },
  { lon: -118.30, lat: 35.50, alt: 1000, label: 'RTB-2' },
  { lon: -118.80, lat: 34.80, alt: 500,  label: 'RTB-3' },
  { lon: -119.30, lat: 34.25, alt: 200,  label: 'MARSHAL' },
];

// Phase boundaries (waypoint indices)
// Transit: 0-2, Canyon: 3-11, Egress: 12-14, RTB: 15-18
export const PHASE_BOUNDARIES = {
  transit: { start: 0, end: 2 },       // DEPARTURE through DESCENT
  canyonRun: { start: 3, end: 11 },    // CANYON-INGRESS through TARGET
  egress: { start: 12, end: 14 },      // EGRESS-1 through EGRESS-3
  rtb: { start: 15, end: 18 },         // RTB-1 through MARSHAL
};

// SAM sites along canyon ridgelines
// Positioned on high ground overlooking the canyon
export const SAM_POSITIONS: SAMPosition[] = [
  // Canyon entrance defense
  {
    id: 'sam-1',
    lon: -117.39, lat: 36.35, alt: 700,
    detectionRadius: 8000,
    altitudeThreshold: 150,
    label: 'SA-15 GAUNTLET',
    modelUrl: './sam-patriot.glb',
  },
  // Left ridge SAMs
  {
    id: 'sam-2',
    lon: -117.35, lat: 36.37, alt: 750,
    detectionRadius: 8000,
    altitudeThreshold: 150,
    label: 'SA-11 GADFLY',
    modelUrl: './sam-s300.glb',
  },
  {
    id: 'sam-3',
    lon: -117.29, lat: 36.39, alt: 680,
    detectionRadius: 8000,
    altitudeThreshold: 150,
    label: 'SA-6 GAINFUL',
    modelUrl: './sam-s300.glb',
  },
  // Right ridge SAMs
  {
    id: 'sam-4',
    lon: -117.25, lat: 36.40, alt: 720,
    detectionRadius: 8000,
    altitudeThreshold: 150,
    label: 'SA-15 GAUNTLET',
    modelUrl: './sam-patriot.glb',
  },
  {
    id: 'sam-5',
    lon: -117.22, lat: 36.43, alt: 690,
    detectionRadius: 8000,
    altitudeThreshold: 150,
    label: 'SA-11 GADFLY',
    modelUrl: './sam-s300.glb',
  },
  // Target area defense — toughest
  {
    id: 'sam-6',
    lon: -117.18, lat: 36.45, alt: 650,
    detectionRadius: 10000,
    altitudeThreshold: 100,
    label: 'SA-10 GRUMBLE',
    modelUrl: './sam-s300.glb',
  },
  // Egress gauntlet — these fire as you try to escape
  {
    id: 'sam-7',
    lon: -117.16, lat: 36.49, alt: 700,
    detectionRadius: 10000,
    altitudeThreshold: 100,
    label: 'SA-10 GRUMBLE',
    modelUrl: './sam-s300.glb',
  },
  {
    id: 'sam-8',
    lon: -117.22, lat: 36.51, alt: 750,
    detectionRadius: 8000,
    altitudeThreshold: 150,
    label: 'SA-6 GAINFUL',
    modelUrl: './sam-patriot.glb',
  },
];

// Countermeasure loadout
export const COUNTERMEASURES = {
  chaff: 8,
  flares: 8,
  chaffDefeatChance: 0.70, // 70% chance to defeat a radar-guided missile
  flareDefeatChance: 0.80, // 80% chance to defeat an IR-guided missile
  evasionBonus: 0.15,      // +15% defeat chance when maneuvering hard
};

// Missile parameters
export const MISSILE_CONFIG = {
  speed: 350,           // m/s
  turnRate: 2.5,        // radians/s — limited so evasion works
  lockOnTime: 4.0,      // seconds to achieve lock (warning period)
  reloadTime: 6.0,      // seconds between shots per SAM
  proximityFuse: 25,    // meters — hit detection radius
  maxRange: 5000,       // meters — missile self-destructs beyond this
  trailLength: 10,      // visual trail segments
};

// Bomb target — the ventilation shaft at the end of the canyon
export const BOMB_TARGET = {
  lon: -117.17,
  lat: 36.46,
  alt: 350, // ground level at target
  lockDistance: 5000,  // meters — target lock engages at this range
  dropDistance: 500,   // meters — optimal drop point
  hitRadius: 100,      // meters — counts as a hit within this radius
  label: 'TARGET ALPHA',
};

// Flight profile for the canyon run (overrides autopilot)
export const MAVERICK_FLIGHT_PROFILE = {
  transitSpeed: 200,    // m/s during transit
  canyonSpeed: 150,     // m/s during canyon run
  egressSpeed: 250,     // m/s during egress (fast to escape SAMs)
  rtbSpeed: 180,        // m/s during return
};
