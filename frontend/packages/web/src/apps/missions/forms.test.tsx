// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SceneStore } from '../../scene/store';
import { ControllerContext } from './context';
import { MissionsController } from './controller';
import { ReportForm } from './forms';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
function setup() {
  const c = new MissionsController({ store: new SceneStore() });
  c.store.setState({ missionId: 'mission-a', sampleStoryboard: false });
  render(<ControllerContext.Provider value={c}><ReportForm /></ControllerContext.Provider>);
  fireEvent.change(screen.getByLabelText('Time (UTC)'), { target: { value: '2026-11-05T12:00' } });
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Original title' } });
  fireEvent.change(screen.getByLabelText('Body'), { target: { value: 'Original body' } });
  return c;
}
it('keeps report text after a real controller save failure (F23)', async () => {
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 503 }));
  const c = setup();
  fireEvent.submit(screen.getByRole('form', { name: 'Add report' }));
  await waitFor(() => expect(c.state.error).toContain('not available'));
  expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('Original title');
  expect((screen.getByLabelText('Body') as HTMLInputElement).value).toBe('Original body');
  c.dispose();
});
it('does not clear text edited while a successful submission was pending', async () => {
  const c = setup();
  let done!: (saved: boolean) => void;
  vi.spyOn(c, 'addReport').mockImplementation(() => new Promise((resolve) => { done = resolve; }));
  fireEvent.submit(screen.getByRole('form', { name: 'Add report' }));
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'New title' } });
  await act(async () => done(true));
  expect((screen.getByLabelText('Title') as HTMLInputElement).value).toBe('New title');
  expect((screen.getByLabelText('Body') as HTMLInputElement).value).toBe('');
  c.dispose();
});
