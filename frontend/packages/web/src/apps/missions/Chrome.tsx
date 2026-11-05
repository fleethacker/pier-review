import { cn } from '../../lib/cn';
import { useController, useMissions } from './context';
import { chipBtn } from './parts';
import { StoryboardBottom, StoryboardSide, StoryboardSidebar } from './StoryboardPanels';
import { TransitBottom, TransitSide, TransitSidebar, TRANSIT_DISCLAIMER } from './TransitPanels';
import type { Tab } from './controller';

const TABS: [Tab, string][] = [['storyboard', 'Storyboard'], ['transit', 'Transit']];

export function Sidebar() {
  const c = useController();
  const tab = useMissions((s) => s.tab);
  return (
    <div>
      <div role="tablist" aria-label="Missions views" className="mb-3 flex">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            id={`missions-tab-${id}`}
            aria-selected={tab === id}
            aria-controls="missions-tabpanel"
            tabIndex={tab === id ? 0 : -1}
            className={cn(chipBtn(tab === id), 'flex-1')}
            onClick={() => c.setTab(id)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') c.setTab(tab === 'storyboard' ? 'transit' : 'storyboard');
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="missions-tabpanel" aria-labelledby={`missions-tab-${tab}`}>
        {tab === 'storyboard' ? <StoryboardSidebar /> : <TransitSidebar />}
      </div>
    </div>
  );
}

export function Side() {
  const tab = useMissions((s) => s.tab);
  return tab === 'storyboard' ? <StoryboardSide /> : <TransitSide />;
}

export function Bottom() {
  const tab = useMissions((s) => s.tab);
  return tab === 'storyboard' ? <StoryboardBottom /> : <TransitBottom />;
}

export function Banner() {
  const tab = useMissions((s) => s.tab);
  const sample = useMissions((s) => (s.tab === 'storyboard' ? s.sampleStoryboard : s.sampleTransit));
  return (
    <div className="flex items-center gap-3">
      {sample && (
        <span role="status" className="rounded-sm border border-mil-red/60 bg-mil-red/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-mil-red" title="The backend returned 501 or could not be reached; showing a labeled MOCK fixture.">
          Sample data (mock fixture, backend unavailable)
        </span>
      )}
      <span className="hidden text-[10px] text-mil-amber md:inline">{tab === 'transit' ? TRANSIT_DISCLAIMER : 'Recorded positions are displayed as given; nothing is extrapolated.'}</span>
    </div>
  );
}
