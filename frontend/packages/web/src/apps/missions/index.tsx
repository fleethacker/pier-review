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
  title: 'Mission storyboard and port transit',
  description: 'Replay a mission from its track, images and reports; simulate and play back port transits.',
  start(host): AppInstance {
    const controller = new MissionsController(host);
    void controller.init();
    return {
      Sidebar: withController(controller, Sidebar, 'Sidebar'),
      Side: withController(controller, Side, 'Key'),
      Bottom: withController(controller, Bottom, 'Timeline'),
      Banner: withController(controller, Banner, 'Banner'),
      onEdit: () => {},
      dispose: () => controller.dispose(),
    };
  },
};
