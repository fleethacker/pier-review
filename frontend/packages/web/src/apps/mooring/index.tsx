import type { ComponentType } from 'react';
import type { AppDefinition, AppInstance } from '../../scene/app';
import { Banner } from './Banner';
import { MooringController } from './controller';
import { Dashboard } from './panels/Dashboard';
import { DataKey } from './panels/DataKey';
import { Overlay } from './panels/Overlay';
import { ControllerContext } from './panels/context';
import { Sidebar } from './Sidebar';

function withController(controller: MooringController, Component: ComponentType): ComponentType {
  const Wrapped = () => (
    <ControllerContext.Provider value={controller}>
      <Component />
    </ControllerContext.Provider>
  );
  Wrapped.displayName = `Mooring(${Component.displayName ?? Component.name})`;
  return Wrapped;
}

export const mooringApp: AppDefinition = {
  id: 'mooring',
  title: 'Mooring assistant',
  description: 'Plan a mooring: ship, pier, lines, tugs and the safety sheet.',
  start(host): AppInstance {
    const controller = new MooringController(host);
    void controller.init();
    return {
      Sidebar: withController(controller, Sidebar),
      Side: withController(controller, DataKey),
      Bottom: withController(controller, Dashboard),
      Banner: withController(controller, Banner),
      Overlay: withController(controller, Overlay),
      onEdit: (edit) => controller.onEdit(edit),
      dispose: () => controller.dispose(),
    };
  },
};
