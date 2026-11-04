export interface BaseLocation {
  id: string;
  name: string;
  country: string;
  longitude: number;
  latitude: number;
  altitude: number;
  heading: number;
  missionId?: string; // Special mission trigger (e.g., 'maverick')
}

export const LOCATIONS: BaseLocation[] = [
  { id: 'sf', name: 'Golden Gate Bridge', country: 'USA', longitude: -122.4783, latitude: 37.8199, altitude: 600, heading: 270 },
  { id: 'paris', name: 'Eiffel Tower', country: 'France', longitude: 2.2945, latitude: 48.8584, altitude: 700, heading: 90 },
  { id: 'nyc', name: 'Times Square', country: 'USA', longitude: -73.9855, latitude: 40.7580, altitude: 800, heading: 0 },
  { id: 'tokyo', name: 'Tokyo Tower', country: 'Japan', longitude: 139.7454, latitude: 35.6586, altitude: 700, heading: 180 },
  { id: 'dubai', name: 'Burj Khalifa', country: 'UAE', longitude: 55.2744, latitude: 25.1972, altitude: 1000, heading: 270 },
  { id: 'london', name: 'Big Ben', country: 'UK', longitude: -0.1246, latitude: 51.5007, altitude: 600, heading: 45 },
  { id: 'sydney', name: 'Opera House', country: 'Australia', longitude: 151.2153, latitude: -33.8568, altitude: 600, heading: 135 },
  { id: 'rio', name: 'Christ the Redeemer', country: 'Brazil', longitude: -43.2105, latitude: -22.9519, altitude: 1000, heading: 90 },
  { id: 'giza', name: 'Great Pyramid', country: 'Egypt', longitude: 31.1342, latitude: 29.9792, altitude: 600, heading: 0 },
  { id: 'reykjavik', name: 'Reykjavik', country: 'Iceland', longitude: -21.8174, latitude: 64.1265, altitude: 600, heading: 180 },
  { id: 'singapore', name: 'Marina Bay', country: 'Singapore', longitude: 103.8591, latitude: 1.2868, altitude: 600, heading: 90 },
  { id: 'barcelona', name: 'Sagrada Familia', country: 'Spain', longitude: 2.1744, latitude: 41.4036, altitude: 600, heading: 0 },
  { id: 'goth', name: 'Gothenburg', country: 'Sweden', longitude: 11.9746, latitude: 57.7089, altitude: 600, heading: 180 },
];

let _baseLocation: BaseLocation = LOCATIONS[0]; // Default to SF

export function setBaseLocation(location: BaseLocation): void {
  _baseLocation = location;
}

export function getBaseLocation(): BaseLocation {
  return _baseLocation;
}
