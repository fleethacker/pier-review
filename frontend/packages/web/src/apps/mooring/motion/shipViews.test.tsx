// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MotionController } from './controller';
import { MotionView } from './MotionView';
import { adaptFrame } from './frames';
import type { SimFrame, SimScene } from './frames';
import { catalog, controls, loading, workspace } from './workspace.test-fixtures';

const dir = path.resolve(__dirname, '../../../../../../../contract/examples/modeling');
const raw = JSON.parse(readFileSync(path.join(dir, 'sim_frame.json'), 'utf8')) as SimFrame;
const scene = JSON.parse(readFileSync(path.join(dir, 'sim_scene.json'), 'utf8')) as SimScene;
afterEach(cleanup);

describe('Simultaneous ship views', () => {
  it('shows all three sections beside the map and hides them independently without resetting the viewport', () => {
    const c = new MotionController({ faceBearingDeg: () => 90, tugIds: () => [], lineNumbers: () => [], layoutKey: () => 'test', ensureScenario: async () => null, initialState: () => null });
    c.state.set({ open: true, source: 'live', workspace, catalog, scene, frame: adaptFrame({ ...raw, controls, loading }, { faceBearingDeg: 90 }), link: 'open', lifecycle: 'paused' });
    render(<MotionView controller={c} workspace />);
    const map = screen.getByRole('img', { name: 'Plan view of the ship, pier, lines and tugs' });
    const dock = screen.getByRole('region', { name: 'Ship views' });
    const legend = screen.getByText('Vector / line key · lbf, ft/s, ft/s²').closest('details')!;
    expect(legend.open).toBe(false);
    for (const view of ['forward', 'aft', 'side']) expect(within(dock).getByRole('img', { name: new RegExp(`${view} hull`) })).toBeTruthy();
    fireEvent.keyDown(map, { key: 'ArrowLeft' }); const panned = map.getAttribute('viewBox');
    fireEvent.click(screen.getByRole('button', { name: 'Hide details' }));
    expect(legend.open).toBe(false);
    expect(screen.getByRole('region', { name: 'Ship views' })).toBe(dock);
    fireEvent.click(screen.getByRole('button', { name: 'Hide ship views' }));
    expect(screen.queryByRole('region', { name: 'Ship views' })).toBeNull();
    expect(screen.getByRole('img', { name: 'Plan view of the ship, pier, lines and tugs' })).toBe(map);
    expect(map.getAttribute('viewBox')).toBe(panned);
    fireEvent.click(screen.getByRole('button', { name: 'Show ship views' }));
    expect(screen.getByRole('region', { name: 'Ship views' })).toBeTruthy();
    expect(map.getAttribute('viewBox')).toBe(panned);
    fireEvent.click(screen.getByRole('button', { name: 'Forward' }));
    expect(screen.getAllByRole('img', { name: /forward hull/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Map' }));
    expect(screen.getByRole('region', { name: 'Ship views' })).toBeTruthy();
  });
});
