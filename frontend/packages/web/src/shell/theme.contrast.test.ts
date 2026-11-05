import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { COLORS, STATUS_COLOR } from './theme';

const luminance = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const tailwind = readFileSync(path.resolve(__dirname, '../../tailwind.config.js'), 'utf8');
const token = (name: string) => new RegExp(`\\b${name}: '(#[0-9a-fA-F]{6})'`).exec(tailwind)![1];

describe('text contrast (WCAG AA, 4.5:1 for small text)', () => {
  const backgrounds = { page: token('bg'), panel: token('panel') };

  it('keeps the tailwind and theme dim colours in step', () => {
    expect(token('dim')).toBe(COLORS.dim);
  });

  it.each(Object.entries(backgrounds))('dim, body and amber text read on the %s background', (_name, bg) => {
    expect(contrast(token('dim'), bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('text'), bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(STATUS_COLOR.AMBER, bg)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('cyan'), bg)).toBeGreaterThanOrEqual(4.5);
  });

  it('keeps dim text dimmer than body text', () => {
    expect(luminance(token('dim'))).toBeLessThan(luminance(token('text')));
  });
});
