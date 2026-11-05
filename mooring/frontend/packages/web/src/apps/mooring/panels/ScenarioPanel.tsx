import { useState } from 'react';
import { Button, Panel, Select, inputClass } from '../../../shell/ui';
import { useController, useMooring } from './context';

export function ScenarioPanel() {
  const c = useController();
  const scenarios = useMooring((s) => s.scenarios);
  const current = useMooring((s) => s.scenarioId);
  const [name, setName] = useState('');
  return (
    <Panel title="Saved scenarios" className="space-y-2 p-4">
      <div className="flex gap-2">
        <input
          className={inputClass}
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Scenario name"
        />
        <Button
          size="sm"
          disabled={!name.trim()}
          onClick={() => void c.saveScenario(name.trim()).then(() => setName(''))}
        >
          Save
        </Button>
      </div>
      {scenarios.length > 0 && (
        <Select
          value={current ?? ''}
          onChange={(v) => v && void c.loadScenario(v)}
          options={[
            { value: '', label: 'Load a saved scenario…', disabled: true },
            ...scenarios.map((sc) => ({ value: sc.scenario_id, label: sc.name })),
          ]}
        />
      )}
    </Panel>
  );
}
