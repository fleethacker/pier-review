// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api')>()), modeling: { POST: vi.fn() } }));
vi.mock('../streams', () => ({ openJsonStream: () => ({ send: () => true, close: () => undefined }) }));

import { Frame } from '../panels/Overlay';
import { MotionController } from './controller';
import type { MotionHost } from './controller';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { MotionView } from './MotionView';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const load = <T,>(n: string): T => JSON.parse(readFileSync(path.join(dir, n), 'utf8')) as T;
const raw = load<SimFrame>('sim_frame.json');
const scene = load<SimScene>('sim_scene.json');

const host: MotionHost = {
  faceBearingDeg: () => 90,
  tugIds: () => ['T1'],
  lineNumbers: () => [1],
  layoutKey: () => 'k',
  ensureScenario: async () => 's',
  initialState: () => null,
};

afterEach(cleanup);

function open(patch: Partial<ReturnType<MotionController['state']['get']>> = {}) {
  const c = new MotionController(host);
  c.state.set({ open: true, source: 'live', link: 'open', lifecycle: 'running', scene, frame: adaptFrame(raw, { faceBearingDeg: 90 }), ...patch });
  render(<MotionView controller={c} />);
  return c;
}

describe('MotionView accessibility', () => {
  it('is a labelled modal dialog that takes focus in plan view', () => {
    open();
    const dialog = screen.getByRole('dialog', { name: 'Motion view' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(dialog);
  });

  it('is not modal in map view, where the map stays usable', () => {
    open({ view: 'map' });
    expect(screen.getByRole('dialog', { name: 'Motion view' }).getAttribute('aria-modal')).toBe('false');
  });

  it('closes on Escape even when a button has focus, but not while a select is focused', () => {
    const c = open();
    const close = vi.spyOn(c, 'close');
    const resume = screen.getByRole('button', { name: 'Resume' });
    const tug = screen.getByRole('combobox', { name: 'Tug' });
    fireEvent.keyDown(tug, { key: 'Escape' });
    expect(close).not.toHaveBeenCalled();
    resume.focus();
    fireEvent.keyDown(resume, { key: 'Escape' });
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('announces validity, provenance, link and session in a polite status region that changes only with them', () => {
    const c = open();
    const status = screen.getAllByRole('status').find((el) => /Frame validity/.test(el.textContent ?? ''))!;
    expect(status.getAttribute('aria-live')).toBe('polite');
    expect(status.textContent).toBe('Frame validity limited, provenance mock, link open, session running');
    // A new frame with the same validity and provenance leaves the announcement untouched.
    act(() => c.state.set({ frame: adaptFrame({ ...raw, t_s: raw.t_s + 0.1 }, { faceBearingDeg: 90 }) }));
    expect(status.textContent).toBe('Frame validity limited, provenance mock, link open, session running');
    act(() => c.state.set({ link: 'closed', lifecycle: 'paused' }));
    expect(status.textContent).toContain('link closed, session paused');
  });

  it('labels the controls, groups and live regions', () => {
    open();
    expect(screen.getByRole('group', { name: 'Frame validity and provenance' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'View' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Tug' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Line' })).toBeTruthy();
    expect(screen.getByRole('spinbutton', { name: /Force/ })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: /Push from/ })).toBeTruthy();
    expect(screen.getByRole('spinbutton', { name: /Start offset/ })).toBeTruthy();
    expect(screen.getByRole('complementary', { name: 'Frame readouts' })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Plan view of the ship, pier, lines and tugs' })).toBeTruthy();
  });

  it('makes alert lists and lifecycle messages live regions, and errors alerts', () => {
    const f = adaptFrame({ ...raw, structured_alerts: [{ code: 'X', severity: 'AMBER', message: 'Line 3 is taut', element_ids: [] }] } as SimFrame, { faceBearingDeg: 90 });
    open({ frame: f, error: 'link lost', lifecycleMessage: 'paused by operator' });
    const list = screen.getByRole('list', { name: 'Alerts in this frame' });
    expect(list.getAttribute('aria-live')).toBe('polite');
    expect(within(list).getByText(/Line 3 is taut/)).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('link lost');
    expect(screen.getByText('Session: paused by operator').getAttribute('role')).toBe('status');
  });

  it('gives the replay scrubber a spoken value', () => {
    open({ source: 'recording', recording: { id: 'r', durationS: 60, label: 'fixture', frames: [raw] }, cursorS: 12 });
    expect(screen.getByRole('slider', { name: 'Scrub the recording' }).getAttribute('aria-valuetext')).toBe('12.0 of 60 seconds');
  });
});

describe('map view notes', () => {
  it('says what is drawn, labels the water surface as display only, and lists what is not drawn', () => {
    open({ view: 'map', notDrawn: ['roll and pitch'] });
    const note = screen.getByText(/Map view draws position/).closest('[role="status"]')!;
    expect(note.textContent).toMatch(/Water surface drawn at .* MLLW from the frame: display only/);
    expect(note.textContent).toMatch(/Not drawn:.*roll and pitch/);
  });

  it('does not mention a water surface when the frame carries no water level', () => {
    const f = adaptFrame({ ...raw, environment: null } as SimFrame, { faceBearingDeg: 90 });
    open({ view: 'map', frame: f, notDrawn: ['water surface'] });
    expect(screen.queryByText(/Water surface drawn/)).toBeNull();
  });
});

describe('dialog frame', () => {
  it('is a labelled modal dialog that closes on Escape', () => {
    const onClose = vi.fn();
    render(<Frame title="Result abc" onClose={onClose}><p>body</p></Frame>);
    const dialog = screen.getByRole('dialog', { name: 'Result abc' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(dialog);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
