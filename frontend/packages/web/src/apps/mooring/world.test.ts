import { describe, expect, it } from 'vitest';
import { clusterPorts, groupPorts, mapBackground, mapPosition, mercator, portAt, portLabel } from './world';

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
    for (const [lat, lon] of [[36.9, -76.3], [32.7, -117.1], [21.4, -158], [35.3, 139.7], [36.6, -6.3], [76.54, -68.84], [1.27, 103.79], [25.0, 55.07]]) {
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

  it('merges ports that would overlap on the map into one marker that lists all their berths', () => {
    const ports = groupPorts([
      site('ADEN', "Ma'alla Jetty (Port of Aden, Yemen)", 12.7996, 45.0016),
      site('DJI', 'Doraleh north quay (Port of Djibouti)', 11.6004, 43.0631),
      site('CTG', 'Muelle 2 (Port of Cartagena, Colombia)', 10.405, -75.5312),
      site('CUR', 'Tula pier (Willemstad, Curacao)', 12.1053, -68.9445),
      site('NOR', 'Pier 12 (NAVSTA Norfolk)', 36.9575, -76.3317),
    ]);
    expect(ports).toHaveLength(5);
    const clusters = clusterPorts(ports);
    expect(clusters).toHaveLength(3);
    const red = clusters.find((c) => c.berths.some((b) => b.berthId === 'ADEN'))!;
    expect(red.berths.map((b) => b.berthId)).toEqual(['ADEN', 'DJI']);
    expect(red.label).toBe('Port of Aden, Yemen / Port of Djibouti');
    expect(red.lat).toBeCloseTo((12.7996 + 11.6004) / 2);
    const caribbean = clusters.find((c) => c.berths.some((b) => b.berthId === 'CTG'))!;
    expect(caribbean.berths.map((b) => b.berthId)).toEqual(['CTG', 'CUR']);
    expect(clusters.find((c) => c.berths.some((b) => b.berthId === 'NOR'))!.berths).toHaveLength(1);
  });

  it('leaves well-separated ports alone', () => {
    const ports = groupPorts([site('A', 'A (Norfolk)', 36.9, -76.3), site('B', 'B (San Diego)', 32.7, -117.1)]);
    expect(clusterPorts(ports)).toEqual(ports);
  });

  it('lines the background image up with the marker positions', () => {
    const bg = mapBackground();
    const band = 1 / bg.aspectRatio;
    const yMin = mercator(79, 0).y;
    // The top of the box is the band's north edge and the bottom is its south edge.
    expect(mapPosition(79, 0).y).toBeCloseTo(0);
    expect(mapPosition(-66.6, 0).y).toBeGreaterThan(0.99);
    // CSS: image height H = boxHeight / band, offset p% places p% of the image at p% of the box: top = p * (box - H).
    const p = parseFloat(bg.positionY) / 100;
    const imageHeight = 1 / band;
    // To 4 decimals: the CSS string keeps 3 decimals of a percent, a twentieth of a pixel on this map.
    expect(p * (1 - imageHeight)).toBeCloseTo(-yMin * imageHeight, 4);
    expect(parseFloat(bg.size.split(' ')[1])).toBeCloseTo(100 / band, 2);
  });
});
