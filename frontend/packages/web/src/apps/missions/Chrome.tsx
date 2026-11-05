import { useMissions } from './context';
import { StoryboardBottom, StoryboardSide, StoryboardSidebar } from './StoryboardPanels';
import { CameraSidebar, CameraSide, CameraBanner } from './CameraPanels';
import { TransitBottom, TransitSide, TransitSidebar, TRANSIT_DISCLAIMER } from './TransitPanels';

/** Panels for the current tab. The shell's tab bar chooses the tab. */
export function Sidebar() {
  const tab = useMissions((s) => s.tab);
  return tab === 'storyboard' ? <StoryboardSidebar /> : tab === 'transit' ? <TransitSidebar /> : <CameraSidebar />;
}

export function Side() {
  const tab = useMissions((s) => s.tab);
  return tab === 'storyboard' ? (
    <StoryboardSide />
  ) : tab === 'transit' ? (
    <TransitSide />
  ) : (
    <CameraSide />
  );
}

export function Bottom() {
  const tab = useMissions((s) => s.tab);
  return tab === 'storyboard' ? <StoryboardBottom /> : <TransitBottom />;
}

export function Banner() {
  const tab = useMissions((s) => s.tab);
  const cameraOn = useMissions((s) => s.cameraOn);
  const sample = useMissions((s) =>
    s.tab === 'storyboard' ? s.sampleStoryboard : s.sampleTransit,
  );
  return (
    <div className="flex items-center gap-3">
      {(tab === 'camera' || (tab === 'transit' && cameraOn)) && <CameraBanner />}
      {sample && (
        <span
          role="status"
          className="rounded-sm border border-mil-red/60 bg-mil-red/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-mil-red"
          title="The backend returned 501 or could not be reached; showing a labeled MOCK fixture."
        >
          Sample data (mock fixture, backend unavailable)
        </span>
      )}
      <span className="hidden text-[10px] text-mil-amber md:inline">
        {tab === 'transit' || tab === 'camera'
          ? TRANSIT_DISCLAIMER
          : 'Recorded positions are displayed as given; nothing is extrapolated.'}
      </span>
    </div>
  );
}
