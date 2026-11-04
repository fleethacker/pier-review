import { Button, Field, Panel, inputClass } from '../../../shell/ui';
import { lengthFromDisplay, lengthToDisplay, lengthUnit, useUnitSystem } from '../units';
import type { Environment } from '../types';
import { useController, useMooring } from './context';

const FIELDS: { key: keyof Environment; label: string; step: number; min?: number; max?: number; length?: boolean }[] = [
  { key: 'wind_speed_kt', label: 'Wind (kt)', step: 1, min: 0 },
  { key: 'wind_gust_kt', label: 'Gust (kt)', step: 1, min: 0 },
  { key: 'wind_from_true_deg', label: 'Wind from (°T)', step: 5, min: 0, max: 359 },
  { key: 'current_speed_kt', label: 'Current (kt)', step: 0.1, min: 0 },
  { key: 'current_set_true_deg', label: 'Current toward (°T)', step: 5, min: 0, max: 359 },
  { key: 'water_level_mllw_ft', label: 'Water level (ft MLLW)', step: 0.1, length: true },
];

export function EnvPanel() {
  useUnitSystem();
  const c = useController();
  const env = useMooring((s) => s.env);
  if (!env) return null;
  return (
    <Panel title="Environment" className="space-y-3 p-4">
      <div className="grid grid-cols-2 gap-3">
        {FIELDS.map((f) => (
          <Field key={f.key} label={f.length ? `Water level (${lengthUnit()} MLLW)` : f.label}>
            <input
              type="number"
              className={inputClass}
              step={f.step}
              min={f.min}
              max={f.max}
              value={f.length ? Number(lengthToDisplay(Number(env[f.key] ?? 0)).toFixed(2)) : Number(env[f.key] ?? 0)}
              onChange={(e) => c.setEnv({ [f.key]: f.length ? lengthFromDisplay(Number(e.target.value)) : Number(e.target.value) })}
            />
          </Field>
        ))}
      </div>
      <div className="flex items-center justify-between text-[10px] text-mil-dim">
        <span>
          Source: {env.source}
          {env.tide_stage ? ` · ${env.tide_stage} tide` : ''}
        </span>
        <Button size="sm" variant="secondary" onClick={() => void c.refreshEnv()}>
          Reload
        </Button>
      </div>
    </Panel>
  );
}
