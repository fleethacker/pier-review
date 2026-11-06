import { useCallback, useEffect, useState } from 'react';
import { cn } from '../../lib/cn';
import { Button, Select } from '../../shell/ui';
import { useController, useExercise } from './context';
import { deleteLocal, listLocal, loadLocal, saveLocal, slugify } from './library';
import { PRESET_SCENARIOS } from './scenarios';
import { parseScenario } from './scenarioJson';
import { deleteShared, listShared, loadShared, saveShared } from './serverApi';
import type { LibraryItem } from './serverApi';

type Where = 'local' | 'shared';

const when = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
};

/** Saved scenarios: in this browser, or in a library on the server that everyone using the app can open. */
export function Library() {
  const c = useController();
  const scenario = useExercise((s) => s.scenario);
  const [where, setWhere] = useState<Where>(c.library.where);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [sharedUp, setSharedUp] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const id = slugify(scenario.name);

  const refresh = useCallback(async () => {
    if (where === 'local') {
      setItems(listLocal());
      return;
    }
    try {
      setItems(await listShared());
      setSharedUp(true);
    } catch (e) {
      // Back to this browser, but keep offering the shared library: the server may only have blinked.
      c.library.where = 'local';
      setWhere('local');
      setMessage({ ok: false, text: `The shared library is not available: ${e instanceof Error ? e.message : String(e)}` });
    }
  }, [where, c]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Find out once whether there is a shared library, so the choice is only offered when it works.
  useEffect(() => {
    let cancelled = false;
    listShared().then(
      () => !cancelled && setSharedUp(true),
      () => !cancelled && setSharedUp(false),
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const unsaved = () => {
    const original = PRESET_SCENARIOS.find((p) => p.id === scenario.id);
    const now = JSON.stringify(scenario);
    return original ? JSON.stringify(original) !== now : c.library.snapshot !== now;
  };

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setMessage(null);
    try {
      setMessage({ ok: true, text: await fn() });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      const existing = items.find((i) => i.id === id);
      const mine = c.library.origin && c.library.origin.where === where && c.library.origin.id === id;
      if (existing && !mine && !window.confirm(`Replace the saved scenario “${existing.name}”?`)) return 'Not saved.';
      const body = JSON.parse(c.exportJson()) as unknown;
      const saved = where === 'local' ? saveLocal(id, body) : await saveShared(id, body, mine ? c.library.origin!.updatedAt : undefined);
      c.library.origin = { where, id, updatedAt: saved.updatedAt };
      c.library.snapshot = JSON.stringify(scenario);
      await refresh();
      return `${saved.created ? 'Saved' : 'Updated'} “${scenario.name}” ${where === 'local' ? 'in this browser' : 'in the shared library'}.`;
    });

  const load = (item: LibraryItem) =>
    run(async () => {
      if (unsaved() && !window.confirm('Loading this discards your unsaved changes to the scenario on screen. Continue?')) return 'Not loaded.';
      const got = where === 'local' ? loadLocal(item.id) : await loadShared(item.id);
      if (!got) throw new Error('That scenario is no longer saved.');
      const parsed = parseScenario(JSON.stringify(got.scenario));
      c.loadScenario(parsed);
      c.library.origin = { where, id: item.id, updatedAt: got.updatedAt };
      c.library.snapshot = JSON.stringify(parsed);
      return `Loaded “${parsed.name}”.`;
    });

  const remove = (item: LibraryItem) =>
    run(async () => {
      if (!window.confirm(`Delete the saved scenario “${item.name}”? This cannot be undone.`)) return 'Not deleted.';
      if (where === 'local') deleteLocal(item.id);
      else await deleteShared(item.id);
      if (c.library.origin?.id === item.id && c.library.origin.where === where) c.library.origin = null;
      await refresh();
      return `Deleted “${item.name}”.`;
    });

  return (
    <details className="space-y-2" aria-label="Saved scenarios">
      <summary className="mil-label cursor-pointer">Saved scenarios</summary>
      <div className="space-y-2 pt-2">
        {sharedUp && (
          <Select
            value={where}
            onChange={(v) => {
              setMessage(null);
              c.library.where = v as Where;
              setWhere(v as Where);
            }}
            options={[
              { value: 'local', label: 'In this browser' },
              { value: 'shared', label: 'Shared library (everyone using the app)' },
            ]}
          />
        )}
        <div className="flex items-center gap-2">
          <Button size="sm" disabled={busy} onClick={() => void save()}>
            Save “{scenario.name}”
          </Button>
          <span className="truncate text-[10px] text-mil-dim" title={id}>
            as {id}
          </span>
        </div>
        {items.length === 0 ? (
          <p className="text-[10px] text-mil-dim">Nothing saved {where === 'local' ? 'in this browser' : 'in the shared library'} yet.</p>
        ) : (
          <ul className="space-y-1" aria-label="Saved scenario list">
            {items.map((item) => (
              <li key={item.id} className={cn('flex items-center justify-between gap-2 border p-1.5', item.id === id ? 'border-mil-cyan/50' : 'border-mil-border')}>
                <div className="min-w-0">
                  <div className="truncate text-[11px] text-white">{item.name}</div>
                  <div className="text-[10px] text-mil-dim">
                    {item.units} units · {when(item.updatedAt)}
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="secondary" disabled={busy} aria-label={`Load ${item.name}`} onClick={() => void load(item)}>
                    Load
                  </Button>
                  <button className="px-1 text-mil-dim hover:text-mil-red" disabled={busy} aria-label={`Delete ${item.name}`} onClick={() => void remove(item)}>
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {message && (
          <p role={message.ok ? 'status' : 'alert'} className={cn('text-[10px]', message.ok ? 'text-mil-dim' : 'text-mil-red')}>
            {message.text}
          </p>
        )}
        {where === 'local' && <p className="text-[10px] leading-snug text-mil-dim">Kept in this browser only. Download the JSON to move a scenario to another computer.</p>}
      </div>
    </details>
  );
}
