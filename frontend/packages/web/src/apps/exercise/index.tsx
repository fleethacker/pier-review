import type { ComponentType } from 'react';
import type { AppDefinition, AppInstance } from '../../scene/app';
import { Banner } from './Banner';
import { Bottom } from './Bottom';
import { ExerciseController } from './controller';
import { ControllerContext } from './context';
import { MapCanvas } from './MapCanvas';
import { Side } from './Side';
import { Sidebar } from './Sidebar';

function withController(controller: ExerciseController, Component: ComponentType): ComponentType {
  const Wrapped = () => (
    <ControllerContext.Provider value={controller}>
      <Component />
    </ControllerContext.Provider>
  );
  Wrapped.displayName = `Exercise(${Component.displayName ?? Component.name})`;
  return Wrapped;
}

export const exerciseApp: AppDefinition = {
  id: 'exercise',
  title: 'Exercise simulator',
  description: 'Replay a naval exercise in 3D on a Mapbox map: ships, routes, formations and conditions you can configure.',
  canvas: 'custom',
  start(host): AppInstance {
    const controller = new ExerciseController(host);
    controller.startLoop();
    return {
      Canvas: withController(controller, MapCanvas),
      Sidebar: withController(controller, Sidebar),
      Side: withController(controller, Side),
      Bottom: withController(controller, Bottom),
      Banner: withController(controller, Banner),
      dispose: () => controller.dispose(),
    };
  },
};
