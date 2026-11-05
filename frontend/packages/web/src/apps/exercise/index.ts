import type { AppDefinition } from '../../scene/app';

// Only the description lives here. The app itself (the editor, the simulator, the red team, the map) is a separate chunk that
// loads when the tab is first opened, so the mooring tab does not pay for it.
export const exerciseApp: AppDefinition = {
  id: 'exercise',
  title: 'Exercise simulator',
  description: 'Replay a naval exercise in 3D on a Mapbox map: ships, routes, formations and conditions you can configure.',
  canvas: 'custom',
  tabs: [
    { id: 'scenario', label: 'Scenario' },
    { id: 'environment', label: 'Environment' },
    { id: 'forces', label: 'Forces' },
  ],
  physics: ['Ship kinematics and routes', 'Sensors and detection', 'Engagement and damage', 'Monte Carlo red team'],
  async start(host) {
    const { startExercise } = await import('./runtime');
    return startExercise(host);
  },
};
