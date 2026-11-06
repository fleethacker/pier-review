import type { ComponentType } from 'react';
import type { AppHost, AppInstance } from './lib/app';
import { Bottom } from './Bottom';
import { DataCatalog } from './DataCatalog';
import { installErrorReporting } from './clientErrors';
import { ExerciseController } from './controller';
import { ControllerContext } from './context';
import { MapCanvas } from './MapCanvas';
import { RedTeamPanel } from './RedTeam';
import { SetupDrawer } from './SetupDrawer';
import { Side } from './Side';
import { StoryboardPanel } from './StoryboardPanel';

/**
 * What floats over the map. The storyboard view keeps the map and the event feed; everything else — the scenario and the
 * red team under Setup, the sources under the catalog — opens here on top of it.
 */
function Overlays() {
  return (
    <>
      <SetupDrawer />
      <RedTeamPanel />
      <StoryboardPanel />
      <DataCatalog />
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

/** Everything the exercise view is made of. A separate chunk, so the page frame paints before the simulator does. */
export function startExercise(host: AppHost): AppInstance {
  const controller = new ExerciseController(host);
  controller.startLoop();
  const stopReporting = installErrorReporting();
  return {
    // No left column: the map runs the width of the page, with the feed on the right and the storyboard underneath.
    Canvas: withController(controller, MapCanvas),
    Side: withController(controller, Side),
    Bottom: withController(controller, Bottom),
    Overlay: withController(controller, Overlays),
    dispose: () => {
      stopReporting();
      controller.dispose();
    },
  };
}
