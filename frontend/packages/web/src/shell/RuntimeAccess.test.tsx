// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RuntimeAccess } from './RuntimeAccess';
import { credentialState, runtimeAuthHeaders, setRuntimeCredential } from '../lib/credentials';
import { openJsonStream } from '../apps/mooring/streams';

afterEach(() => { cleanup(); setRuntimeCredential(''); vi.unstubAllGlobals(); });
it('accepts a runtime user key, keeps it out of persistent storage and URLs, and clears it', () => {
  render(<RuntimeAccess />);
  fireEvent.click(screen.getByText('Access: gateway / local'));
  fireEvent.change(screen.getByLabelText('API credential'), { target: { value: 'runtime-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply credential' }));
  expect(runtimeAuthHeaders()).toEqual({ Authorization: 'Bearer runtime-secret' });
  expect((screen.getByLabelText('API credential') as HTMLInputElement).value).toBe('');
  expect(JSON.stringify(localStorage)).not.toContain('runtime-secret');
  expect(JSON.stringify(sessionStorage)).not.toContain('runtime-secret');
  expect(window.location.href).not.toContain('runtime-secret');
  fireEvent.click(screen.getByRole('button', { name: 'Clear credential' }));
  expect(runtimeAuthHeaders()).toEqual({});
});
it('does not attempt native WebSocket authentication with a bearer key', () => {
  setRuntimeCredential('runtime-secret');
  const socket = vi.fn(); vi.stubGlobal('WebSocket', socket);
  const status = vi.fn();
  const stream = openJsonStream('ws://localhost/ws/sim/s', vi.fn(), status);
  expect(socket).not.toHaveBeenCalled();
  expect(status).toHaveBeenCalledWith('error');
  expect(stream.send('pause')).toBe(false);
  expect(credentialState.get().configured).toBe(true);
});
