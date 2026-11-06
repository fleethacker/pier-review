import type { AppDefinition } from './lib/app';

// Only the description lives here. The app itself (the editor, the simulator, the red team, the map) is a separate chunk,
// so the page frame paints before the simulator and the map are parsed.
export const exerciseApp: AppDefinition = {
  id: 'exercise',
  title: 'Exercise simulator',
  description: 'Gather what a naval exercise produced into one timeline, play it back on a 3D map, and tell the story of it.',
  physics: ['Ship kinematics and routes', 'Sensors and detection', 'Engagement and damage', 'Monte Carlo red team'],
  async start(host) {
    const { startExercise } = await import('./runtime');
    return startExercise(host);
  },
};
