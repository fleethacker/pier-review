import type { ComponentType } from 'react';
import type { AppDefinition, AppInstance } from '../../scene/app';
import { ErrorBoundary } from '../../shell/ui';
import { Banner, Bottom, Side, Sidebar } from './Chrome';
import { ControllerContext } from './context';
import { MissionsController } from './controller';

function withController(controller: MissionsController, Component: ComponentType, name: string): ComponentType {
  const Wrapped = () => (
    <ControllerContext.Provider value={controller}>
      <ErrorBoundary name={name}>
        <Component />
      </ErrorBoundary>
    </ControllerContext.Provider>
  );
  Wrapped.displayName = `Missions(${name})`;
  return Wrapped;
}

export const missionsApp: AppDefinition = {
  id: 'missions',
  title: 'Mission simulation',
  description:
    'Backup camera: predict where the ship goes from its live state and forcing. Storyboard: replay a recorded mission with its images and reports. Transit: simulate and play back port transits.',
  tabs: [
    { id: 'camera', label: 'Camera' },
    { id: 'storyboard', label: 'Storyboard' },
    { id: 'transit', label: 'Transit' },
  ],
  physics: ['3-DOF vessel dynamics', 'Tugs and autopilot', 'Wind, current and tide', 'Track prediction'],
  start(host): AppInstance {
    const controller = new MissionsController(host);
    void controller.init();
    return {
      Sidebar: withController(controller, Sidebar, 'Sidebar'),
      Side: withController(controller, Side, 'Key'),
      Bottom: withController(controller, Bottom, 'Timeline'),
      Banner: withController(controller, Banner, 'Banner'),
      onEdit: () => {},
      setTab: (id) => {
        if (id === 'camera' || id === 'storyboard' || id === 'transit') controller.setTab(id);
      },
      onTabChange: (listener) => {
        let last = controller.state.tab;
        return controller.store.subscribe(() => {
          const tab = controller.state.tab;
          if (tab !== last) {
            last = tab;
            listener(tab);
          }
        });
      },
      dispose: () => controller.dispose(),
    };
  },
};
