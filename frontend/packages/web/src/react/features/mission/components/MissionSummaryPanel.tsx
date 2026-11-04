import type { WaypointLog, AnalysisResult } from '../hooks/useMissionState';

interface MissionSummaryPanelProps {
  waypoints: WaypointLog[];
  totalDetections: number;
  startTime: number | null;
  analysis: AnalysisResult | null;
  isAnalyzing: boolean;
  onDismiss: () => void;
}

const THREAT_COLORS = {
  low: 'text-mil-green border-mil-green/30 bg-mil-green/10',
  medium: 'text-mil-amber border-mil-amber/30 bg-mil-amber/10',
  high: 'text-mil-red border-mil-red/30 bg-mil-red/10',
};

export function MissionSummaryPanel({
  waypoints,
  totalDetections,
  startTime,
  analysis,
  isAnalyzing,
  onDismiss,
}: MissionSummaryPanelProps) {
  const duration = startTime ? Math.floor((Date.now() - startTime) / 1000) : 0;
  const mins = String(Math.floor(duration / 60)).padStart(2, '0');
  const secs = String(duration % 60).padStart(2, '0');

  return (
    <div className="fixed inset-0 z-[160] bg-black/80 flex items-center justify-center animate-fade-in">
      <div className="max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto">
        <div className="glass-panel mil-brackets p-6 space-y-5">
          {/* Header */}
          <div className="text-center space-y-1">
            <div className="mil-label text-mil-green tracking-[0.3em]">MISSION COMPLETE</div>
            <h2 className="text-lg font-mono font-bold text-mil-cyan tracking-wider text-glow">
              ISR MISSION REPORT
            </h2>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-3 gap-3">
            <div className="glass-panel p-3 text-center">
              <div className="mil-label mb-1">WAYPOINTS</div>
              <div className="text-lg text-mil-cyan font-mono">{waypoints.length}</div>
            </div>
            <div className="glass-panel p-3 text-center">
              <div className="mil-label mb-1">TARGETS</div>
              <div className="text-lg text-mil-cyan font-mono">{totalDetections}</div>
            </div>
            <div className="glass-panel p-3 text-center">
              <div className="mil-label mb-1">DURATION</div>
              <div className="text-lg text-mil-cyan font-mono">{mins}:{secs}</div>
            </div>
          </div>

          {/* Per-waypoint breakdown */}
          <div className="space-y-2">
            <div className="mil-label">WAYPOINT INTEL</div>
            {waypoints.map((wp, i) => {
              const classCounts: Record<string, number> = {};
              wp.detections.forEach(d => {
                classCounts[d.class] = (classCounts[d.class] || 0) + 1;
              });
              const summary = Object.entries(classCounts)
                .map(([cls, count]) => `${count} ${cls}`)
                .join(', ');

              return (
                <div key={i} className="flex items-start gap-3 px-3 py-2 bg-mil-panel/50 border border-mil-border rounded-sm">
                  <span className="text-[10px] text-mil-cyan font-mono font-bold min-w-[45px]">
                    WP-{String(i + 1).padStart(2, '0')}
                  </span>
                  <div className="flex-1">
                    <div className="text-[10px] text-mil-dim font-mono">
                      {wp.lat.toFixed(4)}, {wp.lon.toFixed(4)}
                    </div>
                    <div className="text-[11px] text-mil-text font-mono">
                      {wp.detections.length > 0 ? summary : 'No targets detected'}
                    </div>
                  </div>
                  <span className="text-[10px] text-mil-dim font-mono">
                    {wp.detections.length} TGT
                  </span>
                </div>
              );
            })}
          </div>

          {/* AI Analysis */}
          <div className="space-y-2">
            <div className="mil-label text-mil-amber">INTELLIGENCE ANALYSIS</div>
            {isAnalyzing ? (
              <div className="flex items-center gap-2 px-3 py-3 bg-mil-panel/50 border border-mil-border rounded-sm">
                <div className="w-4 h-4 border-2 border-mil-amber/30 border-t-mil-amber rounded-full animate-spin" />
                <span className="text-[10px] text-mil-amber font-mono tracking-wider animate-pulse">
                  GENERATING INTEL REPORT...
                </span>
              </div>
            ) : analysis ? (
              <div className="space-y-3">
                {/* Threat level */}
                <div className={`inline-block px-3 py-1 border rounded-sm text-[10px] font-mono font-bold tracking-wider ${THREAT_COLORS[analysis.threat_level]}`}>
                  THREAT LEVEL: {analysis.threat_level.toUpperCase()}
                </div>

                {/* Summary */}
                <div className="text-[11px] text-mil-text font-mono leading-relaxed px-3 py-2 bg-mil-panel/50 border border-mil-border rounded-sm">
                  {analysis.summary}
                </div>

                {/* Recommendations */}
                {analysis.recommendations.length > 0 && (
                  <div className="space-y-1">
                    <div className="text-[9px] text-mil-dim font-mono tracking-wider">RECOMMENDATIONS</div>
                    {analysis.recommendations.map((rec, i) => (
                      <div key={i} className="flex items-start gap-2 text-[10px] text-mil-text font-mono">
                        <span className="text-mil-cyan">&gt;</span>
                        <span>{rec}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-[10px] text-mil-dim font-mono px-3 py-2">
                Analysis unavailable
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-center pt-2">
            <button
              onClick={onDismiss}
              className="px-8 py-3 text-[11px] font-mono font-bold tracking-[0.15em] uppercase
                         bg-mil-cyan/20 hover:bg-mil-cyan/30 text-mil-cyan border border-mil-cyan/40
                         hover:border-mil-cyan/60 rounded-sm transition-all"
            >
              NEW MISSION
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
