import { createContext, useContext, useSyncExternalStore } from 'react';
import type { ExerciseController, ExerciseState } from './controller';

export const ControllerContext = createContext<ExerciseController | null>(null);

export function useController(): ExerciseController {
  const c = useContext(ControllerContext);
  if (!c) throw new Error('useController must be used inside the exercise app');
  return c;
}

/** Select from the exercise state. The selector must return a stable value (a primitive or an existing reference). */
export function useExercise<S>(selector: (s: ExerciseState) => S): S {
  return useController().state.use(selector);
}

/** Whole seconds of simulated time. Re-renders once per simulated second, not once per frame. */
export function useClockSecond(): number {
  const c = useController();
  return useSyncExternalStore(c.clock.subscribe, () => Math.floor(c.clock.timeS));
}
