import type { MaverickFailedData } from '../../../../cesium/bridge/types';

interface MaverickFailedProps {
  data: MaverickFailedData;
  onRetry: () => void;
}

export function MaverickFailed({ data, onRetry }: MaverickFailedProps) {
  const minutes = Math.floor(data.time / 60);
  const seconds = Math.floor(data.time % 60);
  const timeStr = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/70">
      <div className="bg-[#1a0a0a]/95 border border-[#ff3333]/30 rounded-sm p-8 max-w-md w-full mx-4 font-mono"
        style={{ boxShadow: '0 0 40px rgba(255, 51, 51, 0.15)' }}>

        <div className="text-center mb-6">
          <div className="text-[10px] tracking-[0.4em] text-[#ff3333] mb-2 animate-pulse">
            MISSION DEBRIEF
          </div>
          <h2 className="text-2xl font-bold text-[#ff3333] tracking-wider mb-2"
            style={{ textShadow: '0 0 20px rgba(255, 51, 51, 0.5)' }}>
            MISSION FAILED
          </h2>
          <div className="text-[#ff6666] text-sm">
            {data.reason === 'missile_hit'
              ? 'Aircraft destroyed by surface-to-air missile'
              : 'Aircraft crashed into terrain'}
          </div>
        </div>

        <div className="space-y-3 text-sm">
          <div className="flex justify-between border-b border-[#3a1a1a] pb-2">
            <span className="text-[#6a3a3a]">TIME OF LOSS</span>
            <span className="text-[#ff6666]">{timeStr}</span>
          </div>
          <div className="flex justify-between border-b border-[#3a1a1a] pb-2">
            <span className="text-[#6a3a3a]">PHASE</span>
            <span className="text-[#ff6666]">{data.phase.toUpperCase().replace('_', ' ')}</span>
          </div>
        </div>

        <button
          onClick={onRetry}
          className="w-full mt-6 py-3 bg-[#ff3333]/10 border border-[#ff3333]/30 text-[#ff3333]
                     text-xs tracking-[0.3em] rounded-sm hover:bg-[#ff3333]/20 transition-colors
                     pointer-events-auto cursor-pointer"
        >
          RETRY MISSION
        </button>
      </div>
    </div>
  );
}
