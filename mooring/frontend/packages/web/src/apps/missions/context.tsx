import { createContext, useContext } from 'react';
import type { MissionsController, MissionsState } from './controller';
import { useStore } from './store';

export const ControllerContext = createContext<MissionsController | null>(null);

export function useController(): MissionsController {
  const c = useContext(ControllerContext);
  if (!c) throw new Error('MissionsController missing from context');
  return c;
}

export function useMissions<T>(selector: (s: MissionsState) => T): T {
  return useStore(useController().store, selector);
}
