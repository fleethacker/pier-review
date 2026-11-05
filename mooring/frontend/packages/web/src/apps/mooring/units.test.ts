import { afterEach, describe, expect, it } from 'vitest';
import { fmt, lengthFromDisplay, lengthToDisplay, lengthUnit, setUnitSystem } from './units';

afterEach(() => setUnitSystem('navy'));

describe('unit system', () => {
  it('shows Navy units by default', () => {
    expect(fmt.ft(509.5, 1)).toBe('509.5 ft');
    expect(fmt.lbf(26043)).toBe('26,043 lbf');
    expect(fmt.hp(7000)).toBe('7,000 hp');
    expect(fmt.longTons(9500)).toBe('9,500 LT');
    expect(lengthUnit()).toBe('ft');
  });

  it('converts at the display edge when metric is chosen', () => {
    setUnitSystem('metric');
    expect(fmt.ft(100)).toBe('30 m');
    expect(fmt.ft(509.5, 1)).toBe('155.3 m');
    expect(fmt.lbf(100000)).toBe('444.8 kN');
    expect(fmt.hp(7000)).toBe('5,220 kW');
    expect(fmt.longTons(9500)).toBe('9,652 t');
    expect(fmt.lbfPerFt(150000)).toBe('2189.1 kN/m');
    // Speeds and angles are the same in both systems.
    expect(fmt.kt(12.4, 1)).toBe('12.4 kt');
    expect(fmt.deg(224.4)).toBe('224°');
  });

  it('round-trips typed lengths back to feet for the API', () => {
    setUnitSystem('metric');
    expect(lengthUnit()).toBe('m');
    expect(lengthFromDisplay(lengthToDisplay(12))).toBeCloseTo(12, 9);
    expect(lengthFromDisplay(3.6576)).toBeCloseTo(12, 6);
  });
});
