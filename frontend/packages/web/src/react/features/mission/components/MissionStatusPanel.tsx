import type { WaypointLog } from '../hooks/useMissionState';

interface MissionStatusPanelProps {
  currentWaypointIndex: number;
  waypoints: WaypointLog[];
  totalDetections: number;
  startTime: number | null;
  onAbort: () => void;
}

export function MissionStatusPanel({
  currentWaypointIndex,
  waypoints,
  totalDetections,
  onAbort,
}: MissionStatusPanelProps) {
  const progress = waypoints.length > 0 ? (currentWaypointIndex / waypoints.length) * 100 : 0;
  const currentWP = currentWaypointIndex < waypoints.length ? waypoints[currentWaypointIndex] : null;

  return (
    <div className="fixed left-8 top-12 z-50 w-64 pointer-events-auto animate-fade-in">
      <div className="glass-panel mil-brackets p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-mil-green animate-pulse" />
            <span className="mil-label text-mil-amber">MISSION ACTIVE</span>
          </div>
        </div>

        {/* Status */}
        <div className="text-[11px] text-mil-cyan font-mono tracking-wider">
          {currentWP?.scanning
            ? `SCANNING WP-${String(currentWaypointIndex + 1).padStart(2, '0')}`
            : currentWaypointIndex < waypoints.length
              ? `EN ROUTE WP-${String(currentWaypointIndex + 1).padStart(2, '0')}`
              : 'COMPLETING...'
          }
        </div>

        {/* Progress bar */}
        <div className="w-full h-1.5 bg-mil-panel rounded-sm border border-mil-border overflow-hidden">
          <div
            className="h-full bg-mil-green transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="text-[9px] text-mil-dim font-mono text-right">
          {currentWaypointIndex} / {waypoints.length} WAYPOINTS
        </div>

        {/* Waypoint list */}
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {waypoints.map((wp, i) => (
            <div
              key={i}
              className={`flex items-center gap-2 px-2 py-1 rounded-sm text-[10px] font-mono ${
                i === currentWaypointIndex
                  ? 'bg-mil-cyan/10 text-mil-cyan'
                  : wp.scanned
                    ? 'text-mil-green'
                    : 'text-mil-dim'
              }`}
            >
              <span className="w-3 text-center">
                {wp.scanning ? '◉' : wp.scanned ? '✓' : i === currentWaypointIndex ? '▸' : '○'}
              </span>
              <span>WP-{String(i + 1).padStart(2, '0')}</span>
              {wp.scanned && (
                <span className="ml-auto text-mil-dim">{wp.detections.length} TGT</span>
              )}
            </div>
          ))}
        </div>

        {/* Stats */}
        <div className="border-t border-mil-border pt-2 flex justify-between">
          <span className="text-[9px] text-mil-dim font-mono">DETECTIONS</span>
          <span className="text-[11px] text-mil-cyan font-mono">{totalDetections}</span>
        </div>

        {/* Abort */}
        <button
          onClick={onAbort}
          className="w-full py-2 text-[10px] font-mono tracking-wider text-mil-red border border-mil-red/30
                     hover:bg-mil-red/10 rounded-sm transition-colors uppercase"
        >
          ABORT MISSION
        </button>
      </div>
    </div>
  );
}
