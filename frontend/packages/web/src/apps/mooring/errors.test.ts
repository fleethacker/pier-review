import { describe, expect, it } from 'vitest';
import { describeError } from './api';

const err = (msg: string) => new Error(msg);

describe('describeError', () => {
  it('turns a physics-tool timeout into a plain sentence', () => {
    const raw = '504 /api/agents/api/v1/safety-sheets: {"detail":"{\\"code\\": \\"timeout\\", \\"message\\": \\"Tool \'limit_envelope\' exceeded its 30 s timeout.\\", \\"timeout_s\\": 30.0}"}';
    expect(describeError(err(raw))).toBe('A calculation took too long (limit_envelope passed its 30 s limit). The machine may be busy: try again in a moment.');
  });

  it('explains busy, unavailable, gateway and missing-item responses', () => {
    expect(describeError(err('429 /x: {}'))).toMatch(/busy/);
    expect(describeError(err('503 /x: {}'))).toMatch(/not available/);
    expect(describeError(err('502 /x: {}'))).toMatch(/proxy/);
    expect(describeError(err('504 /x: {}'))).toMatch(/too long/);
    expect(describeError(err('404 /x: {}'))).toMatch(/not found/);
  });

  it('keeps the server reason for rejected requests', () => {
    expect(describeError(err('422 /x: {"detail":[{"msg":"Input should be \'berthing\'"}]}'))).toMatch(/rejected the request: Input should be/);
    expect(describeError(err('422 /x: {}'))).toBe('The service rejected the request as invalid.');
  });

  it('handles network failures, cancellation and unknown errors', () => {
    expect(describeError(new TypeError('Failed to fetch'))).toMatch(/Could not reach the service/);
    expect(describeError(new DOMException('x', 'AbortError'))).toBe('Cancelled.');
    expect(describeError(err('something odd'))).toBe('something odd');
    expect(describeError('plain string')).toBe('plain string');
    // 237 characters plus an ellipsis.
    expect(describeError(err('x'.repeat(400)))).toBe(`${'x'.repeat(237)}…`);
  });
});
