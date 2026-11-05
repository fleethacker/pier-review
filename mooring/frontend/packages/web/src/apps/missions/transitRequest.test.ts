import { describe, expect, it } from 'vitest';
import { samplePreset } from './fixtures';
import { parseRequestText, setMaxSpeed, setRouteSpeed, setVesselMode } from './transitRequest';

const req = samplePreset.request;

describe('transit request editing', () => {
  it('own_thrust drops tug fields the server would reject', () => {
    const r = setVesselMode(req, 1, 'own_thrust');
    expect(r.vessels[1].mode).toBe('own_thrust');
    expect(r.vessels[1].tug_assist).toBeUndefined();
    expect(r.vessels[1].tug_commands).toEqual([]);
  });
  it('tug_assisted adds an auto assist and leaves the input untouched', () => {
    const r = setVesselMode(req, 0, 'tug_assisted');
    expect(r.vessels[0].tug_assist?.policy).toBe('auto');
    expect(req.vessels[0].mode).toBe('own_thrust');
  });
  it('sets max speed and a route speed', () => {
    expect(setMaxSpeed(req, 0, 9).vessels[0].propulsion?.max_speed_kt).toBe(9);
    expect(setRouteSpeed(req, 0, 1, 3).vessels[0].route[1].speed_kt).toBe(3);
  });
  it('validates the JSON editor text', () => {
    expect(parseRequestText('{')).toHaveProperty('error');
    expect(parseRequestText('{"vessels":[]}')).toHaveProperty('error');
    expect(parseRequestText(JSON.stringify(req))).toHaveProperty('request');
  });
});
