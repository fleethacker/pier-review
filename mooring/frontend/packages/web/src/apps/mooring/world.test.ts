import { describe, expect, it } from 'vitest';
import { groupPorts, mapPosition, mercator, portAt, portLabel } from './world';

const site = (berthId: string, name: string, lat: number, lon: number) => ({ berthId, name, lat, lon });

describe('world map helpers', () => {
  it('projects the equator and prime meridian to the centre of the world square', () => {
    const m = mercator(0, 0);
    expect(m.x).toBeCloseTo(0.5);
    expect(m.y).toBeCloseTo(0.5);
  });

  it('puts the west of the map left and the north up', () => {
    expect(mapPosition(36.9, -76.3).x).toBeLessThan(mapPosition(35.3, 139.7).x); // Norfolk is west of Yokosuka
    expect(mapPosition(50, 0).y).toBeLessThan(mapPosition(10, 0).y);
  });

  it('keeps every port in the cropped band', () => {
    for (const [lat, lon] of [[36.9, -76.3], [32.7, -117.1], [21.4, -158], [35.3, 139.7], [36.6, -6.3]]) {
      const p = mapPosition(lat, lon);
      expect(p.x).toBeGreaterThan(0);
      expect(p.x).toBeLessThan(1);
      expect(p.y).toBeGreaterThan(0);
      expect(p.y).toBeLessThan(1);
    }
  });

  it('names a port from the parentheses in the berth name', () => {
    expect(portLabel('Mock Pier 12 North face (NAVSTA Norfolk)')).toBe('NAVSTA Norfolk');
    expect(portLabel('Plain name')).toBe('Plain name');
  });

  it('groups the two faces of one pier into one port and keeps distant ports apart', () => {
    const ports = groupPorts([
      site('N', 'Mock Pier 12 North face (NAVSTA Norfolk)', 36.9585, -76.3305),
      site('S', 'Mock Pier 12 South face (NAVSTA Norfolk)', 36.9575, -76.3305),
      site('Y', 'Notional berth, Yokosuka (Fleet Activities Yokosuka)', 35.289, 139.673),
    ]);
    expect(ports).toHaveLength(2);
    expect(ports[0].berths.map((b) => b.berthId)).toEqual(['N', 'S']);
    expect(ports[1].label).toBe('Fleet Activities Yokosuka');
  });

  it('finds the nearest marker within reach and nothing beyond it', () => {
    const centres = [
      { id: 'a', x: 100, y: 100 },
      { id: 'b', x: 112, y: 100 },
    ];
    expect(portAt(110, 100, centres)).toBe('b');
    expect(portAt(101, 100, centres)).toBe('a');
    expect(portAt(300, 300, centres)).toBeNull();
  });
});
