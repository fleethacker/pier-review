import { useState } from 'react';
import { MiniMap } from '../../minimap/components/MiniMap';
import { DetectionPanel } from './DetectionPanel';
import { FlightTrackMap } from '../../tracking/components/FlightTrackMap';
import type { Detection } from '../hooks/useObjectDetection';

type Tab = 'map' | 'below' | 'track';

interface BottomRightPanelProps {
  onDetections?: (detections: Detection[], lat: number, lon: number, alt: number) => void;
}

const TABS: { id: Tab; label: string; icon: JSX.Element }[] = [
  {
    id: 'map',
    label: 'MAP',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4z" />
        <path d="M8 2v16" />
        <path d="M16 6v16" />
      </svg>
    ),
  },
  {
    id: 'below',
    label: 'ISR',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
      </svg>
    ),
  },
  {
    id: 'track',
    label: 'TRACK',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M3 17l4-4 4 4 4-8 6 6" />
        <circle cx="21" cy="15" r="2" />
      </svg>
    ),
  },
];

export function BottomRightPanel({ onDetections }: BottomRightPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>('below');

  return (
    <>
      {/* Tab selector */}
      <div className="fixed bottom-[400px] md:bottom-[390px] right-8 z-50 pointer-events-auto">
        <div className="flex gap-0 glass-panel mil-brackets overflow-hidden">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-[10px] font-mono font-medium tracking-wider transition-all duration-200 ${
                activeTab === tab.id
                  ? 'bg-mil-cyan/10 text-mil-cyan border-b-2 border-mil-cyan'
                  : 'text-mil-dim hover:text-mil-text hover:bg-mil-border/20'
              }`}
              title={tab.label}
            >
              {tab.icon}
              <span className="hidden md:inline">{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'map' && <MiniMap />}

      {/* ISR panel always active so it keeps scanning, hidden when not selected */}
      <div className={`fixed bottom-[72px] right-8 z-50 ${activeTab !== 'below' ? 'hidden' : ''}`}>
        <DetectionPanel isActive={true} onDetections={onDetections} />
      </div>

      {activeTab === 'track' && (
        <div className="fixed bottom-[72px] right-8 z-50">
          <FlightTrackMap />
        </div>
      )}
    </>
  );
}
