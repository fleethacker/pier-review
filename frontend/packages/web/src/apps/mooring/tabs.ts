import type { AppTab } from '../../scene/app';

export type MooringTab = 'setup' | 'conditions' | 'lines' | 'plan' | 'advance' | 'motion';

/** The mooring assistant's tabs, in working order: set up, check conditions, lay lines, plan and review, look ahead, watch it move. */
export const MOORING_TABS: (AppTab & { id: MooringTab })[] = [
  { id: 'setup', label: 'Setup' },
  { id: 'conditions', label: 'Conditions' },
  { id: 'lines', label: 'Lines' },
  { id: 'plan', label: 'Plan & review' },
  { id: 'advance', label: 'Advance (24 h+)' },
  { id: 'motion', label: 'Motion' },
];

export function isMooringTab(id: string): id is MooringTab {
  return MOORING_TABS.some((t) => t.id === id);
}
