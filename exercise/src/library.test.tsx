// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installErrorReporting, reportClientError, resetReported, scrub } from './clientErrors';
import { ControllerContext } from './context';
import { ExerciseController } from './controller';
import { deleteLocal, listLocal, loadLocal, saveLocal, slugify } from './library';
import { Library } from './LibraryPanel';
import { PRESET_SCENARIOS } from './scenarios';
import { ServerError, deleteShared, fetchConfig, listShared, loadShared, saveShared } from './serverApi';

const json = (body: unknown, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => {
  localStorage.clear();
  resetReported();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('names for saved scenarios', () => {
  it('makes ids the server accepts', () => {
    expect(slugify('Missile salvo on a carrier group')).toBe('missile-salvo-on-a-carrier-group');
    expect(slugify('  --Hello, World!--  ')).toBe('hello-world');
    expect(slugify('日本語')).toBe('scenario');
    expect(slugify('x'.repeat(100))).toHaveLength(64);
    expect(slugify('a'.repeat(63) + ' b')).toBe('a'.repeat(63));
    for (const name of ['A/B test', '../../etc', 'ünï', '___', '3rd Fleet']) expect(slugify(name)).toMatch(/^[a-z0-9][a-z0-9_-]{0,63}$/);
  });
});

describe('the browser library', () => {
  it('saves, lists newest first, loads and deletes', () => {
    expect(listLocal()).toEqual([]);
    const a = saveLocal('a', { name: 'Alpha', description: 'first', units: [1, 2, 3] });
    expect(a.created).toBe(true);
    expect(saveLocal('a', { name: 'Alpha 2', units: [] }).created).toBe(false);
    vi.useFakeTimers();
    vi.setSystemTime(new Date(Date.now() + 5000));
    saveLocal('b', { name: 'Beta', units: [1] });
    vi.useRealTimers();
    expect(listLocal().map((i) => [i.id, i.name, i.units])).toEqual([['b', 'Beta', 1], ['a', 'Alpha 2', 0]]);
    expect(loadLocal('b')!.scenario).toEqual({ name: 'Beta', units: [1] });
    expect(loadLocal('zzz')).toBeNull();
    deleteLocal('b');
    expect(listLocal().map((i) => i.id)).toEqual(['a']);
  });

  it('copes with damaged storage and with storage that refuses to save', () => {
    localStorage.setItem('exercise.library.v1', '{not json');
    expect(listLocal()).toEqual([]);
    localStorage.setItem('exercise.library.v1', '[1,2]');
    expect(listLocal()).toEqual([]);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });
    expect(() => saveLocal('a', { name: 'A', units: [] })).toThrow(/would not let the scenario be saved/);
  });
});

describe('the server client', () => {
  it('speaks to the exercise endpoints under the app’s own proxy path', async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith('/config')) return json({ mapboxToken: 'pk.a.b' });
      if (url.endsWith('/scenarios')) return json([]);
      if (init?.method === 'DELETE') return json(null, 204);
      if (init?.method === 'PUT') return json({ id: 'a b', updatedAt: 't', created: true });
      return json({ scenario: { name: 'x' }, updatedAt: 't' });
    });
    expect(await fetchConfig()).toEqual({ mapboxToken: 'pk.a.b' });
    expect(await listShared()).toEqual([]);
    expect(await loadShared('a b')).toEqual({ scenario: { name: 'x' }, updatedAt: 't' });
    await saveShared('a b', { name: 'x' }, '2026-01-01');
    await deleteShared('a b');
    expect(calls.map((c) => c.url.replace(/^https?:\/\/[^/]+/, ''))).toEqual([
      '/api/v1/exercise/config',
      '/api/v1/exercise/scenarios',
      '/api/v1/exercise/scenarios/a%20b',
      '/api/v1/exercise/scenarios/a%20b',
      '/api/v1/exercise/scenarios/a%20b',
    ]);
    expect(JSON.parse(calls[3].init!.body as string)).toEqual({ scenario: { name: 'x' }, baseUpdatedAt: '2026-01-01' });
    expect(JSON.parse(calls[3].init!.body as string)).not.toHaveProperty('x');
  });

  it('turns refusals into errors that say what the server said, and a dead server into one that says so', async () => {
    vi.stubGlobal('fetch', async () => json({ detail: 'Someone saved this scenario after you opened it.' }, 409));
    await expect(saveShared('a', {})).rejects.toMatchObject({ status: 409, message: 'Someone saved this scenario after you opened it.' });
    vi.stubGlobal('fetch', async () => new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }));
    await expect(listShared()).rejects.toMatchObject({ status: 502, message: 'Bad Gateway' });
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('network down');
    });
    await expect(listShared()).rejects.toMatchObject({ status: 0, message: 'Could not reach the server.' });
    await expect(listShared()).rejects.toBeInstanceOf(ServerError);
  });

  it('gives up on a server that never answers', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', (_: string, init: RequestInit) => new Promise((_res, rej) => init.signal!.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))));
    const p = listShared();
    const assertion = expect(p).rejects.toMatchObject({ status: 0, message: 'The server took too long to answer.' });
    await vi.advanceTimersByTimeAsync(8100);
    await assertion;
    vi.useRealTimers();
  });
});

describe('the saved scenarios panel', () => {
  function open(shared?: { items: unknown[]; handler?: (url: string, init?: RequestInit) => Response | Promise<Response> }) {
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      if (!shared) throw new TypeError('no server');
      if (shared.handler) return shared.handler(url, init);
      return json(shared.items);
    });
    const c = new ExerciseController(undefined, PRESET_SCENARIOS[3]);
    const utils = render(
      <ControllerContext.Provider value={c}>
        <Library />
      </ControllerContext.Provider>,
    );
    fireEvent.click(screen.getByText('Saved scenarios'));
    return { c, ...utils };
  }
  const list = () => screen.queryByRole('list', { name: 'Saved scenario list' });

  it('saves the scenario in this browser under its name, and loads it back after a change', async () => {
    const { c } = open();
    fireEvent.click(screen.getByRole('button', { name: /^Save “Missile salvo/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Saved “Missile salvo on a carrier group” in this browser'));
    expect(within(list()!).getByText(/units/)).toBeTruthy();
    expect(listLocal().map((i) => i.id)).toEqual(['missile-salvo-on-a-carrier-group']);

    act(() => c.patchScenario({ name: 'Changed' }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Load Missile salvo on a carrier group' }));
    await waitFor(() => expect(c.state.get().scenario.name).toBe('Missile salvo on a carrier group'));
    expect(c.state.get().errors).toEqual([]);
    expect(c.state.get().scenario.redTeam).toBeTruthy();
  });

  it('asks before throwing away unsaved changes, and before replacing a different saved scenario', async () => {
    saveLocal('other', { ...PRESET_SCENARIOS[0] });
    saveLocal('edited', { name: 'Someone else', units: [] });
    const { c } = open();
    await waitFor(() => expect(list()).toBeTruthy());
    act(() => c.patchScenario({ name: 'Edited' }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByRole('button', { name: `Load ${PRESET_SCENARIOS[0].name}` }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Not loaded.'));
    expect(c.state.get().scenario.name).toBe('Edited');
    expect(confirm.mock.calls[0][0]).toContain('discards your unsaved changes');

    // Saving over a scenario that is not the one on screen asks first.
    fireEvent.click(screen.getByRole('button', { name: /^Save “Edited”/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Not saved.'));
    expect(loadLocal('edited')!.scenario).toEqual({ name: 'Someone else', units: [] });
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: /^Save “Edited”/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Updated “Edited”'));
  });

  it('deletes after asking', async () => {
    saveLocal('gone', { name: 'Gone', units: [] });
    open();
    await waitFor(() => expect(screen.getByLabelText('Delete Gone')).toBeTruthy());
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    fireEvent.click(screen.getByLabelText('Delete Gone'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Not deleted.'));
    expect(listLocal()).toHaveLength(1);
    fireEvent.click(screen.getByLabelText('Delete Gone'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Deleted “Gone”.'));
    expect(listLocal()).toEqual([]);
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it('says what is wrong when a saved scenario cannot be opened', async () => {
    saveLocal('bad', { name: 'Bad one', units: [{ id: 'x' }] });
    const { c } = open();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await waitFor(() => expect(screen.getByLabelText('Load Bad one')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Load Bad one'));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(c.state.get().scenario.name).toBe('Missile salvo on a carrier group');
  });

  it('only offers the shared library when the server has one', async () => {
    open();
    await waitFor(() => expect(screen.queryByRole('combobox')).toBeNull());
    cleanup();
    open({ items: [] });
    await waitFor(() => expect(screen.getByRole('combobox')).toBeTruthy());
  });

  it('saves to the shared library, remembers when it last saw it, and reports a conflict', async () => {
    const puts: { url: string; body: { baseUpdatedAt?: string } }[] = [];
    let respond: Response | null = null;
    const items = [{ id: 'missile-salvo-on-a-carrier-group', name: 'Missile salvo on a carrier group', description: '', units: 12, updatedAt: '2026-05-01T10:00:00.000+00:00' }];
    const { c } = open({
      items,
      handler: (url, init) => {
        if (init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(init.body as string) });
          return respond ?? json({ id: 'x', updatedAt: '2026-05-02T10:00:00.000+00:00', created: false });
        }
        if (url.endsWith('/scenarios')) return json(items);
        return json({ scenario: JSON.parse(c.exportJson()), updatedAt: '2026-05-01T10:00:00.000+00:00' });
      },
    });
    await waitFor(() => expect(screen.getByRole('combobox')).toBeTruthy());
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'shared' } });
    await waitFor(() => expect(screen.getByLabelText('Load Missile salvo on a carrier group')).toBeTruthy());
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    // Not loaded from here yet: replacing asks, and sends no base time.
    fireEvent.click(screen.getByRole('button', { name: /^Save “Missile salvo/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Updated “Missile salvo on a carrier group” in the shared library'));
    expect(puts[0].body.baseUpdatedAt).toBeUndefined();
    // Now it is ours: the next save carries the time we saw, and the server can refuse it.
    respond = json({ detail: 'Someone saved this scenario after you opened it. Load it again, or save under another name.' }, 409);
    fireEvent.click(screen.getByRole('button', { name: /^Save “Missile salvo/ }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Someone saved this scenario after you opened it'));
    expect(puts[1].body.baseUpdatedAt).toBe('2026-05-02T10:00:00.000+00:00');
  });

  it('falls back to this browser, and says so, when the shared library stops answering', async () => {
    let up = true;
    open({ items: [], handler: () => (up ? json([]) : json({ detail: 'down' }, 503)) });
    await waitFor(() => expect(screen.getByRole('combobox')).toBeTruthy());
    up = false;
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'shared' } });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('The shared library is not available: down'));
    await waitFor(() => expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('local'));
    // Still on offer: it may be back next time.
    up = true;
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'shared' } });
    await waitFor(() => expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('shared'));
  });
});

describe('reporting errors to the server', () => {
  const sent = () => {
    const bodies: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(init.body as string));
      return json(null, 204);
    });
    return bodies;
  };

  it('blanks anything shaped like a Mapbox token', () => {
    expect(scrub('bad token pk.eyJ1IjoiYWJj.XyZ-123_ok here sk.abc.def')).toBe('bad token [token] here [token]');
  });

  it('sends each distinct problem once, with the page and browser, never a token', async () => {
    const bodies = sent();
    reportClientError('token', 'rejected pk.aaa.bbb', 'at x (pk.aaa.bbb)');
    reportClientError('token', 'rejected pk.aaa.bbb');
    reportClientError('webgl', 'lost');
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[0]).toMatchObject({ kind: 'token', message: 'rejected [token]', stack: 'at x ([token])' });
    expect(bodies[0].userAgent).toBeTruthy();
    expect(JSON.stringify(bodies)).not.toContain('pk.');
  });

  it('stops after twenty distinct reports, and a failing server never causes another error', async () => {
    const bodies = sent();
    for (let i = 0; i < 30; i++) reportClientError('script', `problem ${i}`);
    await waitFor(() => expect(bodies).toHaveLength(20));
    vi.stubGlobal('fetch', async () => {
      throw new TypeError('offline');
    });
    resetReported();
    expect(() => reportClientError('script', 'x')).not.toThrow();
    await new Promise((r) => setTimeout(r, 0));
  });

  it('picks up uncaught errors and rejected promises while installed, and not after', async () => {
    const bodies = sent();
    const stop = installErrorReporting();
    window.dispatchEvent(new ErrorEvent('error', { message: 'boom', error: new Error('boom') }));
    const rejection = new Event('unhandledrejection') as Event & { reason: unknown };
    rejection.reason = new Error('nope');
    window.dispatchEvent(rejection);
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies.map((b) => [b.kind, b.message])).toEqual([['script', 'boom'], ['promise', 'nope']]);
    stop();
    window.dispatchEvent(new ErrorEvent('error', { message: 'later' }));
    await new Promise((r) => setTimeout(r, 10));
    expect(bodies).toHaveLength(2);
  });
});
