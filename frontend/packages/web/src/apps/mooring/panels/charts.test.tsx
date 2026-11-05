// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { PolarEnvelope } from './charts';

afterEach(cleanup);
it('does not draw a filled holding region across unknown bearings', () => {
  const { container } = render(<PolarEnvelope points={[
    { angle: 0, limit: 20 }, { angle: 90, limit: null }, { angle: 180, limit: 30 }, { angle: 270, limit: 20 },
  ]} />);
  expect(container.querySelector('polygon')).toBeNull();
  expect(container.querySelectorAll('polyline').length).toBeGreaterThan(0);
});
it('renders zero limits and zero current wind without NaN coordinates', () => {
  const { container } = render(<PolarEnvelope points={[0, 90, 180, 270].map((angle) => ({ angle, limit: 0 }))} currentWindKt={0} />);
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
  expect(container.querySelector('svg')).not.toBeNull();
  expect(container.querySelector('circle[stroke-dasharray] title')?.textContent).toBe('Dashed ring: sustained wind 0 kt');
});
