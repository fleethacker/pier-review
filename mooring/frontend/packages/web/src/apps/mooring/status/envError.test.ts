import { afterEach, expect, it, vi } from 'vitest';
import { SceneStore } from '../../../scene/store';

vi.mock('../api', () => ({
  MODELING_BASE: 'http://localhost/api/modeling', AGENTS_BASE: 'http://localhost/api/agents',
  modeling: { GET: vi.fn(), POST: vi.fn() }, agents: { GET: vi.fn(), POST: vi.fn() },
  unwrap: <T,>(r: { data: T }) => r.data, awaitJob: vi.fn(),
  describeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));

import { modeling } from '../api';
import { MooringController } from '../controller';

afterEach(() => vi.resetAllMocks());

it('records an environment failure and clears it on the next good snapshot', async () => {
  const c = new MooringController({ store: new SceneStore() });
  vi.mocked(modeling.GET).mockRejectedValueOnce(new Error('422 unsupported source mode'));
  await c.refreshEnv();
  expect(c.state.get().envError).toMatch(/unsupported source mode/);
  vi.mocked(modeling.GET).mockResolvedValueOnce({ data: { source: 'live', wind_speed_kt: 5 } } as never);
  await c.refreshEnv();
  expect(c.state.get().envError).toBeNull();
  c.dispose();
});
