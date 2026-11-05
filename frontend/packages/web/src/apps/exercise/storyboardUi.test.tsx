// @vitest-environment jsdom
import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Bottom } from './Bottom';
import { ControllerContext } from './context';
import { ExerciseController, PLAYBACK_RATES, presentationRate } from './controller';
import { MapCanvas } from './MapCanvas';
import { PRESET_SCENARIOS } from './scenarios';
import { Side } from './Side';
import { StoryboardPanel } from './Storyboard';
import { STOCK } from './stockImages';

vi.mock('mapbox-gl', () => ({ default: { fake: true } }));
vi.mock('./mapView', () => ({
  ExerciseMapView: class {
    map = {};
    dispose() {}
  },
}));

configure({ asyncUtilTimeout: 10_000 });
vi.setConfig({ testTimeout: 60_000 });

const preset = (id: string) => PRESET_SCENARIOS.find((p) => p.id === id)!;
function mount(ui: React.ReactNode, id = 'salvo-defense') {
  const c = new ExerciseController(undefined, preset(id));
  return { c, ...render(<ControllerContext.Provider value={c}>{ui}</ControllerContext.Provider>) };
}
const open = (id = 'salvo-defense') => {
  const u = mount(<StoryboardPanel />, id);
  act(() => u.c.toggleStoryboard(true));
  return u;
};
const dialog = () => within(screen.getByRole('dialog', { name: 'Storyboard' }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('storyboard in the controller', () => {
  it('builds one from the run, with pictures, and does not re-run the simulation to do it', () => {
    const { c } = mount(<div />, 'sub-ambush');
    const before = c.state.get().active.trajectory;
    act(() => c.generateStoryboard({ max: 6 }));
    const moments = c.storyboard();
    expect(moments.length).toBeGreaterThan(1);
    expect(moments.every((m) => m.image)).toBe(true);
    expect(c.state.get().active.trajectory).toBe(before);
    // The beats reach the run on screen too, so the map can draw them.
    expect(c.state.get().active.scenario.storyboard).toBe(moments);
    expect(c.storyboardProblems()).toEqual([]);
  });

  it('adds a moment at the time on the clock, on the selected unit', () => {
    const { c } = mount(<div />);
    act(() => {
      c.setStoryboard([]);
      c.select('cvn1');
      c.seek(480);
    });
    const id = c.addMoment();
    const m = c.storyboard().find((x) => x.id === id)!;
    expect(m).toMatchObject({ atS: 480, unitId: 'cvn1', title: 'Carrier 1' });
    expect(m.at).toBeUndefined();
    expect(c.state.get().focusedMomentId).toBe(id);
  });

  it('pins a moment to a spot when it hangs on nothing, and swaps between the two', () => {
    const { c } = mount(<div />);
    act(() => {
      c.setStoryboard([]);
      c.select(null);
    });
    const id = c.addMoment();
    expect(c.storyboard()[0].at).toEqual(preset('salvo-defense').center);
    act(() => c.patchMoment(id, { unitId: 'cvn1' }));
    expect(c.storyboard()[0].at).toBeUndefined();
    act(() => c.patchMoment(id, { unitId: undefined }));
    expect(c.storyboard()[0].at).toEqual(preset('salvo-defense').center);
  });

  it('keeps the moments in time order however they are added or moved', () => {
    const { c } = mount(<div />);
    act(() => c.setStoryboard([]));
    const a = c.addMoment({ atS: 300, title: 'late' });
    c.addMoment({ atS: 100, title: 'early' });
    expect(c.storyboard().map((m) => m.title)).toEqual(['early', 'late']);
    act(() => c.patchMoment(a, { atS: 10 }));
    expect(c.storyboard().map((m) => m.title)).toEqual(['late', 'early']);
  });

  it('winds the clock to a moment and selects its unit when one is opened', () => {
    const { c } = mount(<div />);
    const m = c.storyboard().find((x) => x.unitId === 'cvn1')!;
    act(() => c.focusMoment(m.id));
    expect(c.clock.timeS).toBe(m.atS);
    expect(c.state.get().selectedId).toBe('cvn1');
    expect(c.state.get().storyOpen).toBe(true);
    act(() => c.focusMoment('no-such-moment'));
    expect(c.clock.timeS).toBe(m.atS);
  });

  it('removes a moment and forgets it was the one being edited', () => {
    const { c } = mount(<div />);
    const id = c.storyboard()[0].id;
    act(() => c.focusMoment(id));
    act(() => c.removeMoment(id));
    expect(c.storyboard().some((m) => m.id === id)).toBe(false);
    expect(c.state.get().focusedMomentId).toBeNull();
  });

  it('clears every picture without touching the words', () => {
    const { c } = mount(<div />);
    const titles = c.storyboard().map((m) => m.title);
    act(() => c.clearStoryboardImages());
    expect(c.storyboard().every((m) => !('image' in m))).toBe(true);
    expect(c.storyboard().map((m) => m.title)).toEqual(titles);
  });

  it('captures the map into a moment, and says so when there is no map to capture', async () => {
    const { c } = mount(<div />);
    const id = c.storyboard()[0].id;
    expect(c.state.get().canCapture).toBe(false);
    expect(await c.captureInto(id)).toBe(false);
    c.setCapture(async () => 'data:image/jpeg;base64,SHOT');
    expect(c.state.get().canCapture).toBe(true);
    expect(await c.captureInto(id)).toBe(true);
    expect(c.storyboard().find((m) => m.id === id)!.image).toBe('data:image/jpeg;base64,SHOT');
    c.setCapture(null);
    expect(c.state.get().canCapture).toBe(false);
  });

  it('keeps a moment that hung on a unit that is removed, pinned where it was', () => {
    const { c } = mount(<div />);
    act(() => c.setStoryboard([{ id: 'a', atS: 10, holdS: 60, unitId: 'cvn1', title: 'Carrier' }]));
    act(() => c.removeUnit('cvn1'));
    expect(c.storyboard()[0]).toMatchObject({ id: 'a', unitId: undefined });
    expect(c.storyboard()[0].at).toEqual(preset('salvo-defense').center);
    expect(c.state.get().errors).toEqual([]);
  });
});

describe('the storyboard panel', () => {
  it('is not there until opened, and closes from its own button', () => {
    const { c } = mount(<StoryboardPanel />);
    expect(screen.queryByRole('dialog')).toBeNull();
    act(() => c.toggleStoryboard(true));
    expect(screen.getByRole('dialog', { name: 'Storyboard' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close storyboard' }));
    expect(c.state.get().storyOpen).toBe(false);
  });

  it('lists the preset storyboard and edits a moment in place', () => {
    const { c } = open();
    const first = c.storyboard()[0];
    expect(dialog().getByText(`${c.storyboard().length} moments`)).toBeTruthy();
    act(() => c.focusMoment(first.id));
    const title = dialog().getByLabelText('Title of moment 1');
    fireEvent.change(title, { target: { value: 'Opening shot' } });
    expect(c.storyboard()[0].title).toBe('Opening shot');
    const caption = dialog().getByLabelText('Caption of moment 1');
    fireEvent.change(caption, { target: { value: 'New words' } });
    expect(c.storyboard()[0].caption).toBe('New words');
    const hold = dialog().getByLabelText('Stays up for (s)');
    fireEvent.change(hold, { target: { value: '200' } });
    fireEvent.blur(hold);
    expect(c.storyboard()[0].holdS).toBe(200);
  });

  it('builds a storyboard from the run, and can be told how many moments to make', () => {
    const { c } = open('over-the-horizon');
    expect(c.storyboard()).toHaveLength(0);
    expect(dialog().getByText(/Nothing in the storyboard yet/)).toBeTruthy();
    const count = dialog().getByLabelText('Moments');
    fireEvent.change(count, { target: { value: '5' } });
    fireEvent.blur(count);
    fireEvent.click(dialog().getByRole('button', { name: 'Build from the run' }));
    expect(c.storyboard()).toHaveLength(6); // the opening plus five
    expect(dialog().getByRole('button', { name: 'Build it again' })).toBeTruthy();
  });

  it('adds a moment at the time on the clock', () => {
    const { c } = open();
    act(() => c.seek(600));
    const before = c.storyboard().length;
    fireEvent.click(dialog().getByRole('button', { name: /^\+ Add at T\+00:10:00$/ }));
    expect(c.storyboard()).toHaveLength(before + 1);
    expect(c.storyboard().some((m) => m.atS === 600)).toBe(true);
  });

  it('picks a stock picture and shows where it came from', () => {
    const { c } = open();
    const first = c.storyboard()[0];
    act(() => c.focusMoment(first.id));
    const pick = dialog().getByRole('button', { name: `Use the picture: ${STOCK[5].label}` });
    fireEvent.click(pick);
    expect(c.storyboard()[0].image).toBe(STOCK[5].url);
    expect(dialog().getByText(new RegExp(STOCK[5].source.title.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))).toBeTruthy();
    expect(dialog().getByText(/Public domain, from Wikimedia Commons/)).toBeTruthy();
  });

  it('captures the map into a moment, and says why when it cannot', async () => {
    const { c } = open();
    act(() => c.focusMoment(c.storyboard()[0].id));
    const button = () => dialog().getByRole('button', { name: /Capture the map/ });
    expect((button() as HTMLButtonElement).disabled).toBe(true);
    act(() => c.setCapture(async () => 'data:image/jpeg;base64,SHOT'));
    fireEvent.click(button());
    await waitFor(() => expect(c.storyboard()[0].image).toBe('data:image/jpeg;base64,SHOT'));
    act(() =>
      c.setCapture(async () => {
        throw new Error('The map went away.');
      }),
    );
    fireEvent.click(button());
    await waitFor(() => expect(dialog().getByRole('alert').textContent).toContain('The map went away.'));
  });

  it('removes the picture from a moment', () => {
    const { c } = open();
    act(() => c.focusMoment(c.storyboard()[0].id));
    fireEvent.click(dialog().getByRole('button', { name: 'Remove the picture' }));
    expect(c.storyboard()[0].image).toBeUndefined();
    expect(dialog().queryByRole('button', { name: 'Remove the picture' })).toBeNull();
  });

  it('turns the bubbles on the map off and on', () => {
    const { c } = open();
    const box = dialog().getByRole('checkbox', { name: 'Show the bubbles on the map' }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(c.state.get().view.showStory).toBe(false);
  });

  it('opens a printable page, says when the browser blocks it, and downloads it instead', () => {
    const { c } = open();
    const doc = { open: vi.fn(), write: vi.fn(), close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValueOnce({ document: doc } as unknown as Window);
    fireEvent.click(dialog().getByRole('button', { name: 'Storyboard to print' }));
    expect(doc.write.mock.calls[0][0]).toContain('Storyboard:');
    vi.spyOn(window, 'open').mockReturnValueOnce(null);
    fireEvent.click(dialog().getByRole('button', { name: 'Storyboard to print' }));
    expect(dialog().getByRole('alert').textContent).toContain('blocked the window');

    const names: string[] = [];
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => undefined }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    fireEvent.click(dialog().getByRole('button', { name: 'Download the page' }));
    expect(names[0]).toMatch(/^storyboard-.+\.html$/);
    expect(c.storyboard().length).toBeGreaterThan(0);
    vi.unstubAllGlobals();
  });

  it('shows how much the pictures weigh, counting only the ones kept in the scenario', () => {
    const { c } = open();
    expect(dialog().getByText(/0 kB so far/)).toBeTruthy(); // the preset uses stock pictures, which cost nothing
    act(() => c.patchMoment(c.storyboard()[0].id, { image: `data:image/jpeg;base64,${'a'.repeat(40_000)}` }));
    expect(dialog().getByText(/30 kB so far/)).toBeTruthy();
    fireEvent.click(dialog().getByRole('button', { name: 'Clear every picture' }));
    expect(dialog().getByText(/0 kB so far/)).toBeTruthy();
  });

  it('warns about a storyboard that points at a unit that is gone', () => {
    const { c } = open();
    act(() => c.setStoryboard([{ id: 'a', atS: 0, holdS: 60, title: 'Ghost', unitId: 'nobody' }]));
    expect(screen.getByRole('alert').textContent).toContain('does not exist');
  });
});

describe('the storyboard strip on the page', () => {
  const strip = () => within(screen.getByRole('list', { name: 'Storyboard' }));
  const showStory = () => fireEvent.click(screen.getByRole('tab', { name: /^Storyboard/ }));

  it('is a tab beside the contacts and events, counting the moments', () => {
    const { c } = mount(<Bottom />);
    const tab = screen.getByRole('tab', { name: `Storyboard (${c.storyboard().length})` });
    expect(tab.getAttribute('aria-selected')).toBe('false');
    fireEvent.click(tab);
    expect(tab.getAttribute('aria-selected')).toBe('true');
    expect(strip().getAllByRole('listitem')).toHaveLength(c.storyboard().length);
  });

  it('lights the moment that is up as the clock passes it, and dims the ones still to come', () => {
    const { c } = mount(<Bottom />);
    showStory();
    const first = c.storyboard()[0];
    const card = (title: string) => strip().getByRole('button', { name: new RegExp(title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
    act(() => c.seek(first.atS + 5));
    expect(card(first.title).getAttribute('aria-current')).toBe('true');
    const later = c.storyboard().at(-1)!;
    expect(card(later.title).getAttribute('aria-current')).toBeNull();
    expect(card(later.title).className).toContain('opacity-50');
    act(() => c.seek(later.atS + 5));
    expect(card(later.title).getAttribute('aria-current')).toBe('true');
    expect(card(first.title).getAttribute('aria-current')).toBeNull();
  });

  it('winds the clock to a moment when its card is clicked', () => {
    const { c } = mount(<Bottom />);
    showStory();
    const target = c.storyboard()[3];
    fireEvent.click(strip().getByRole('button', { name: new RegExp(target.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }));
    expect(c.clock.timeS).toBe(target.atS);
  });

  it('offers to build one when a scenario has none', () => {
    const { c } = mount(<Bottom />, 'drone-swarm');
    showStory();
    expect(screen.queryByRole('list', { name: 'Storyboard' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Open the storyboard' }));
    expect(c.state.get().storyOpen).toBe(true);
  });

  it('marks the moments on the timeline, and jumps to one when clicked', () => {
    const { c } = mount(<Bottom />);
    const ticks = screen.getAllByRole('button', { name: /^Storyboard moment:/ });
    expect(ticks).toHaveLength(c.storyboard().length);
    fireEvent.click(ticks[2]);
    expect(c.clock.timeS).toBe(c.storyboard()[2].atS);
  });
});

describe('the view panel', () => {
  it('turns the bubbles off and on', () => {
    const { c } = mount(<Side />);
    const box = screen.getByRole('checkbox', { name: 'Storyboard bubbles' }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(c.state.get().view.showStory).toBe(false);
  });
});

describe('presentation mode', () => {
  it('plays the whole run from the top, full screen, at a rate that fits', () => {
    const { c } = mount(<div />);
    act(() => c.seek(900));
    act(() => c.present());
    const s = c.state.get();
    expect(s.presenting).toBe(true);
    expect(s.playing).toBe(true);
    expect(c.clock.timeS).toBe(0);
    // A 25-minute run at 15x plays in about 100 seconds.
    expect(s.rate).toBe(presentationRate(c.state.get().active.scenario.durationS));
    expect(c.state.get().active.scenario.durationS / s.rate).toBeGreaterThan(20);
    expect(c.state.get().active.scenario.durationS / s.rate).toBeLessThan(400);
  });

  it('picks a rate from the ones the app offers, for runs of any length', () => {
    expect(PLAYBACK_RATES).toContain(presentationRate(1500));
    expect(PLAYBACK_RATES).toContain(presentationRate(60));
    expect(presentationRate(60)).toBeLessThan(presentationRate(3600));
    expect(presentationRate(100_000)).toBe(600);
  });

  it('gets the panels out of the way, so nothing covers the map', () => {
    const { c } = mount(<div />);
    act(() => {
      c.toggleRedTeam(true);
      c.toggleStoryboard(true);
      c.setPlacing(true);
    });
    act(() => c.present());
    expect(c.state.get()).toMatchObject({ redTeamOpen: false, storyOpen: false, placing: false, presenting: true });
  });

  it('shows the beat that is up as a caption big enough to read, and changes it as the run goes', () => {
    const { c } = mount(<MapCanvas />);
    act(() => c.present());
    const caption = () => screen.queryByRole('status', { name: 'Storyboard caption' });
    const first = c.storyboard()[0];
    act(() => c.seek(first.atS + 10));
    expect(caption()!.textContent).toContain(first.title);
    const hit = c.storyboard().find((m) => /hit/i.test(m.title))!;
    act(() => c.seek(hit.atS + 5));
    expect(caption()!.textContent).toContain(hit.title);
    expect(caption()!.textContent).toContain('Carrier 1');
  });

  it('shows no caption between beats, or when the bubbles are switched off', () => {
    const { c } = mount(<MapCanvas />);
    act(() => c.present());
    const caption = () => screen.queryByRole('status', { name: 'Storyboard caption' });
    // The preset's beats overlap on purpose, so find a time no beat covers rather than guessing one.
    const last = c.storyboard().at(-1)!;
    const quiet = last.atS + last.holdS + 5;
    expect(quiet).toBeLessThan(c.state.get().active.scenario.durationS);
    act(() => c.seek(quiet));
    expect(caption()).toBeNull();
    act(() => c.seek(c.storyboard()[0].atS + 5));
    expect(caption()).toBeTruthy();
    act(() => c.setView({ showStory: false }));
    expect(caption()).toBeNull();
  });

  it('offers to play again once the run has finished', () => {
    const { c } = mount(<MapCanvas />);
    act(() => c.present());
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();
    act(() => c.seek(c.state.get().active.scenario.durationS));
    const again = screen.getByRole('button', { name: 'Play again' });
    fireEvent.click(again);
    expect(c.clock.timeS).toBe(0);
    expect(c.state.get().playing).toBe(true);
  });

  it('leaves presentation mode from its own button', () => {
    const { c } = mount(<MapCanvas />);
    act(() => c.present());
    fireEvent.click(screen.getByRole('button', { name: 'Exit' }));
    expect(c.state.get().presenting).toBe(false);
  });
});
