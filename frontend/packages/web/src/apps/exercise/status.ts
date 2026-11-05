import { SHIP_CLASSES } from './ships';
import { unitHp } from './sim';
import type { SimEvent } from './sim';
import type { UnitConfig, UnitState } from './types';

export type UnitStatus = 'waiting' | 'active' | 'damaged' | 'destroyed' | 'spent' | 'aborted' | 'disabled';

export const STATUS_LABEL: Record<UnitStatus, string> = {
  waiting: 'Waiting',
  active: 'Active',
  damaged: 'Damaged',
  destroyed: 'Destroyed',
  spent: 'Spent',
  aborted: 'Not launched',
  disabled: 'Left out',
};

/** What is going on with a unit at a moment in the run, in a word. */
export function unitStatus(cfg: UnitConfig, st: UnitState, timeS: number, events: SimEvent[]): UnitStatus {
  if (cfg.disabled) return 'disabled';
  if (st.active) return st.hp <= 0 ? 'destroyed' : st.hp < unitHp(cfg) ? 'damaged' : 'active';
  if (st.hp <= 0) return 'destroyed';
  const waitingUntil = cfg.launch?.atS ?? 0;
  if (timeS < waitingUntil) return 'waiting';
  if (cfg.launch && !events.some((e) => e.type === 'launch' && e.unitId === cfg.id && e.tS <= timeS)) {
    return events.some((e) => e.type === 'aborted' && e.unitId === cfg.id && e.tS <= timeS) ? 'aborted' : 'waiting';
  }
  return 'spent';
}

export const STATUS_COLOR: Record<UnitStatus, string> = {
  waiting: 'text-mil-dim',
  active: 'text-mil-green',
  damaged: 'text-mil-amber',
  destroyed: 'text-mil-red',
  spent: 'text-mil-dim',
  aborted: 'text-mil-amber',
  disabled: 'text-mil-dim',
};

/** An event in a sentence. */
export function eventText(e: SimEvent, name: (id: string) => string): string {
  const unit = name(e.unitId);
  const other = e.otherId ? name(e.otherId) : '';
  const left = e.hpAfter !== undefined ? ` (${Math.round(e.hpAfter)} HP left)` : '';
  switch (e.type) {
    case 'launch':
      return `${other} launched ${unit}`;
    case 'aborted':
      return `${other} was lost before it could launch ${unit}`;
    case 'hit':
      return `${unit} hit ${other}${left}`;
    case 'intercept':
      return `${other} shot down ${unit}`;
    case 'miss':
      return `${unit} missed${other ? ` ${other}` : ''}: ${e.detail ?? 'no effect'}`;
    case 'mine':
      return `${unit} went off under ${other}${left}`;
    case 'destroyed':
      return `${unit} was destroyed${other ? ` by ${other}` : ''}`;
    case 'detected':
      return `${unit} was detected by ${other}`;
    case 'held':
      return `${unit} held: ${e.detail ?? 'not ready'} (${other})`;
  }
}

export const EVENT_COLOR: Record<SimEvent['type'], string> = {
  launch: '#ffd24a',
  aborted: '#9aa7b3',
  hit: '#ff7a1a',
  intercept: '#7ad7ff',
  miss: '#9aa7b3',
  mine: '#ff8a2a',
  destroyed: '#ff3b1a',
  detected: '#5ee6c8',
  held: '#c7a24a',
};

/** The unit worth looking at for an event: the ship or aircraft involved rather than a missile or mine. */
export function eventFocus(e: SimEvent, units: UnitConfig[]): string | undefined {
  const isUnit = (id?: string) => !!id && units.some((u) => u.id === id);
  const platform = (id?: string) => {
    const u = units.find((x) => x.id === id);
    return !!u && !SHIP_CLASSES[u.classId].weapon;
  };
  for (const id of [e.unitId, e.otherId]) if (platform(id)) return id;
  return isUnit(e.unitId) ? e.unitId : undefined;
}
