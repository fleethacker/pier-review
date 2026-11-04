import type { MaverickCompleteData } from '../../../../cesium/bridge/types';

interface MaverickCompleteProps {
  data: MaverickCompleteData;
  onRetry: () => void;
}

export function MaverickComplete({ data, onRetry }: MaverickCompleteProps) {
  const minutes = Math.floor(data.time / 60);
  const seconds = Math.floor(data.time % 60);
  const timeStr = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

  // Rating based on performance
  const rating = data.missilesEvaded >= 3 && data.countermeasuresUsed <= 6
    ? 'MAVERICK'
    : data.missilesEvaded >= 2
    ? 'TOP GUN'
    : data.missilesEvaded >= 1
    ? 'WINGMAN'
    : 'ROOKIE';

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/60">
      <div className="bg-[#0a1628]/95 border border-[#00ff66]/30 rounded-sm p-8 max-w-md w-full mx-4 font-mono"
        style={{ boxShadow: '0 0 40px rgba(0, 255, 102, 0.1)' }}>

        <div className="text-center mb-6">
          <div className="text-[10px] tracking-[0.4em] text-[#00ff66] mb-2">
            MISSION DEBRIEF
          </div>
          <h2 className="text-2xl font-bold text-white tracking-wider mb-1">
            MISSION COMPLETE
          </h2>
          <div className="text-[#ffc107] text-lg tracking-[0.3em]">{rating}</div>
        </div>

        <div className="space-y-3 text-sm">
          <div className="flex justify-between border-b border-[#1a3a5c] pb-2">
            <span className="text-[#4a6a8a]">MISSION TIME</span>
            <span className="text-[#00e5ff]">{timeStr}</span>
          </div>
          <div className="flex justify-between border-b border-[#1a3a5c] pb-2">
            <span className="text-[#4a6a8a]">MISSILES EVADED</span>
            <span className="text-[#00ff66]">{data.missilesEvaded}</span>
          </div>
          <div className="flex justify-between border-b border-[#1a3a5c] pb-2">
            <span className="text-[#4a6a8a]">COUNTERMEASURES USED</span>
            <span className="text-[#ffc107]">{data.countermeasuresUsed}</span>
          </div>
        </div>

        <button
          onClick={onRetry}
          className="w-full mt-6 py-3 bg-[#00ff66]/10 border border-[#00ff66]/30 text-[#00ff66]
                     text-xs tracking-[0.3em] rounded-sm hover:bg-[#00ff66]/20 transition-colors
                     pointer-events-auto cursor-pointer"
        >
          FLY AGAIN
        </button>
      </div>
    </div>
  );
}
