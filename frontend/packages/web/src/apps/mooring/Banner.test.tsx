// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { MooringState } from './controller';

const state = vi.hoisted(() => ({ tab: 'motion', backend: 'modeling', berth: { provenance: { confidence: 'estimated' } } }));
vi.mock('./panels/context', () => ({ useMooring: (selector: (s: MooringState) => unknown) => selector(state as unknown as MooringState) }));
import { Banner } from './Banner';

afterEach(cleanup);

it('uses a compact Motion demo indicator and retains unit controls', () => {
  state.tab = 'motion';
  render(<Banner />);
  expect(screen.getByText('Demo')).toBeTruthy();
  expect(screen.queryByText(/All results limited/)).toBeNull();
  expect(screen.queryByText(/Development model/)).toBeNull();
  expect(screen.queryByText(/berth data:/)).toBeNull();
  expect(screen.getByRole('group', { name: 'Units' })).toBeTruthy();
});

it('preserves the existing qualification banner on other tabs', () => {
  state.tab = 'setup';
  render(<Banner />);
  expect(screen.getByText('All results limited: seed data')).toBeTruthy();
  expect(screen.getByText('Development model, unqualified. Not for operational use.')).toBeTruthy();
  expect(screen.getByText('berth data: estimated')).toBeTruthy();
});
