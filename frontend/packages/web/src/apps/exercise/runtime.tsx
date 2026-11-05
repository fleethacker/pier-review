import type { ComponentType } from 'react';
import type { AppHost, AppInstance } from '../../scene/app';
import { Banner } from './Banner';
import { Bottom } from './Bottom';
import { installErrorReporting } from './clientErrors';
import { ExerciseController } from './controller';
import { ControllerContext } from './context';
import { MapCanvas } from './MapCanvas';
import { RedTeamPanel } from './RedTeam';
import { Side } from './Side';
import { StoryboardPanel } from './StoryboardPanel';
import { Sidebar } from './Sidebar';

/** The panels that float over the map. Both can be opened, but each sits in the same place, so only one shows at a time. */
function Overlays() {
  return (
    <>
      <RedTeamPanel />
      <StoryboardPanel />
    </>
  );
}

function withController(controller: ExerciseController, Component: ComponentType): ComponentType {
  const Wrapped = () => (
    <ControllerContext.Provider value={controller}>
      <Component />
    </ControllerContext.Provider>
  );
  Wrapped.displayName = `Exercise(${Component.displayName ?? Component.name})`;
  return Wrapped;
}

/** Everything the exercise tab is made of. Loaded when the tab is first opened (see index.ts), not with the page. */
export function startExercise(host: AppHost): AppInstance {
  const controller = new ExerciseController(host);
  controller.startLoop();
  const stopReporting = installErrorReporting();
  return {
    Canvas: withController(controller, MapCanvas),
    Sidebar: withController(controller, Sidebar),
    Side: withController(controller, Side),
    Bottom: withController(controller, Bottom),
    Banner: withController(controller, Banner),
    Overlay: withController(controller, Overlays),
    dispose: () => {
      stopReporting();
      controller.dispose();
    },
  };
}
