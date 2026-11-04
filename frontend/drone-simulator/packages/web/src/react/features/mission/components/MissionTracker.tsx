import { useState, useEffect, useMemo } from 'react';
import type { ScanLog, UniqueObject } from '../hooks/useMissionState';

interface MissionTrackerProps {
  scans: ScanLog[];
  totalDetections: number;
  uniqueObjects: UniqueObject[];
  startTime: number | null;
  onViewReport: () => void;
}

export function MissionTracker({
  scans,
  uniqueObjects,
  startTime,
  onViewReport,
}: MissionTrackerProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startTime) return;
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [startTime]);

  const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');
  const scannedCount = scans.length;

  // Aggregate unique objects by class
  const classCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const obj of uniqueObjects) {
      counts[obj.class] = (counts[obj.class] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [uniqueObjects]);

  return (
    <div className="fixed top-10 right-8 z-40 pointer-events-auto animate-fade-in">
      <div className="glass-panel mil-brackets px-4 py-3 w-56 space-y-2">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full bg-mil-green`} />
            <span className="mil-label">ISR TRACKING</span>
          </div>
          <span className="text-[10px] text-white/60 font-mono">{mins}:{secs}</span>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-2 gap-2 text-center border-t border-mil-border pt-2">
          <div>
            <div className="text-[8px] text-white/50 font-mono">SCANS</div>
            <div className="text-sm text-mil-cyan font-mono font-bold">{scannedCount}</div>
          </div>
          <div>
            <div className="text-[8px] text-white/50 font-mono">UNIQUE TARGETS</div>
            <div className="text-sm text-mil-cyan font-mono font-bold">{uniqueObjects.length}</div>
          </div>
        </div>

        {/* Detection breakdown by class */}
        {classCounts.length > 0 && (
          <div className="border-t border-mil-border pt-2 space-y-1">
            <div className="text-[8px] text-white/50 font-mono tracking-wider">CLASSIFIED OBJECTS</div>
            <div className="max-h-32 overflow-y-auto space-y-0.5">
              {classCounts.map(([cls, count]) => (
                <div key={cls} className="flex items-center justify-between px-1 py-0.5">
                  <span className="text-[10px] text-white font-mono uppercase">{cls}</span>
                  <span className="text-[10px] text-mil-cyan font-mono font-bold">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* View report button */}
        {scannedCount > 0 && (
          <button
            onClick={onViewReport}
            className="w-full py-1.5 text-[9px] font-mono font-bold tracking-[0.1em] uppercase
                       bg-mil-cyan/15 hover:bg-mil-cyan/25 text-mil-cyan border border-mil-cyan/30
                       hover:border-mil-cyan/50 rounded-sm transition-all"
          >
            VIEW INTEL REPORT
          </button>
        )}
      </div>
    </div>
  );
}
