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
import { MOORING_TABS, isMooringTab } from './tabs';

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
  title: 'Mooring Assistant',
  description:
    'Plan a mooring at a berth: ship, lines and tugs analyzed against wind, current and tide; an agent plan with an independent safety review and sheet; arrivals 24 h ahead; live berthing motion.',
  tabs: MOORING_TABS,
  physics: ['Mooring line equilibrium', 'Wind and current loads', 'Berthing dynamics', 'Forecast planning'],
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
      setTab: (id) => {
        if (isMooringTab(id)) controller.state.set({ tab: id });
      },
      dispose: () => controller.dispose(),
    };
  },
};
