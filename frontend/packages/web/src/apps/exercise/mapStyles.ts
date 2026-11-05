export type MapStyleId = 'standard' | 'standard-satellite' | 'satellite-streets' | 'dark';

export interface MapStyle {
  id: MapStyleId;
  label: string;
  url: string;
  /** Mapbox Standard styles take a light preset and light the 3D layers themselves. */
  standard: boolean;
}

export const MAP_STYLES: MapStyle[] = [
  { id: 'standard', label: 'Standard (3D lighting)', url: 'mapbox://styles/mapbox/standard', standard: true },
  { id: 'standard-satellite', label: 'Satellite (3D lighting)', url: 'mapbox://styles/mapbox/standard-satellite', standard: true },
  { id: 'satellite-streets', label: 'Satellite streets', url: 'mapbox://styles/mapbox/satellite-streets-v12', standard: false },
  { id: 'dark', label: 'Dark', url: 'mapbox://styles/mapbox/dark-v11', standard: false },
];

export function styleById(id: MapStyleId): MapStyle {
  return MAP_STYLES.find((s) => s.id === id) ?? MAP_STYLES[0];
}

const TOKEN_KEY = 'exercise.mapboxToken';

/** The build-time token wins; otherwise one the user typed in, which stays in this browser only. */
export function getMapboxToken(): string {
  const built = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined)?.trim();
  if (built) return built;
  try {
    return localStorage.getItem(TOKEN_KEY)?.trim() ?? '';
  } catch {
    return '';
  }
}

export function saveMapboxToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token.trim());
  } catch {
    // Storage can be blocked; the token then only lasts until reload.
  }
}
