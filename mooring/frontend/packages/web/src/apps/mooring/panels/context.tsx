import { createContext, useContext } from 'react';
import type { MooringController, MooringState } from '../controller';

export const ControllerContext = createContext<MooringController | null>(null);

export function useController(): MooringController {
  const c = useContext(ControllerContext);
  if (!c) throw new Error('MooringController missing');
  return c;
}

export function useMooring<S>(selector: (s: MooringState) => S): S {
  return useController().state.use(selector);
}

import type { AgentState } from '../agent';

export function useAgent<S>(selector: (s: AgentState) => S): S {
  return useController().agent.state.use(selector);
}
