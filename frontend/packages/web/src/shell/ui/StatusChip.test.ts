import { describe, expect, it } from 'vitest';
import { toStatus } from './StatusChip';

describe('toStatus', () => {
  it('maps common severities onto shell statuses', () => {
    expect(toStatus('green')).toBe('GREEN');
    expect(toStatus('INFO')).toBe('GREEN');
    expect(toStatus('AMBER')).toBe('AMBER');
    expect(toStatus('red')).toBe('RED');
    expect(toStatus(undefined)).toBe('NONE');
    expect(toStatus('weird')).toBe('NONE');
  });
});
