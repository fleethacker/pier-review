import type { ComponentType } from 'react';
import type { AppDefinition, AppInstance } from '../../scene/app';
import { ErrorBoundary } from '../../shell/ui';
import { Banner } from './Banner';
import { MooringController } from './controller';
import { Dashboard } from './panels/Dashboard';
import { DataKey } from './panels/DataKey';
import { Overlay } from './panels/Overlay';
import { ControllerContext } from './panels/context';
import { Sidebar } from './Sidebar';

function withController(controller: MooringController, Component: ComponentType, name: string): ComponentType {
  const Wrapped = () => (
    <ControllerContext.Provider value={controller}>
      <ErrorBoundary name={name}>
        <Component />
      </ErrorBoundary>
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
      Sidebar: withController(controller, Sidebar, 'Sidebar'),
      Side: withController(controller, DataKey, 'Data key'),
      Bottom: withController(controller, Dashboard, 'Dashboard'),
      Banner: withController(controller, Banner, 'Banner'),
      Overlay: withController(controller, Overlay, 'Overlay'),
      onEdit: (edit) => controller.onEdit(edit),
      dispose: () => controller.dispose(),
    };
  },
};
