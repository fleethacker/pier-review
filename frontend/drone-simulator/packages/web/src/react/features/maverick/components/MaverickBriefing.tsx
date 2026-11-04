import { useState } from 'react';

export function MaverickBriefing() {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-black/60">
      <div className="bg-[#0a1628]/95 border border-[#ff3333]/30 rounded-sm p-8 max-w-lg w-full mx-4"
        style={{ boxShadow: '0 0 40px rgba(255, 51, 51, 0.1)' }}>
        {/* Header */}
        <div className="text-center mb-6">
          <div className="text-[10px] tracking-[0.4em] text-[#ff3333] font-mono mb-2 animate-pulse">
            TOP SECRET // EYES ONLY
          </div>
          <h2 className="text-xl font-mono font-bold text-[#ff6666] tracking-wider"
            style={{ textShadow: '0 0 20px rgba(255, 51, 51, 0.3)' }}>
            OPERATION MAVERICK
          </h2>
        </div>

        {/* Mission details */}
        <div className="space-y-4 font-mono text-xs">
          <div className="border-l-2 border-[#ff3333]/30 pl-3">
            <div className="text-[#ff3333] tracking-wider text-[10px] mb-1">OBJECTIVE</div>
            <div className="text-[#8ba4c4]">
              Low-altitude canyon penetration run through hostile SAM corridor.
              Destroy target at end of canyon. Egress under fire.
            </div>
          </div>

          <div className="border-l-2 border-[#ffc107]/30 pl-3">
            <div className="text-[#ffc107] tracking-wider text-[10px] mb-1">THREAT ASSESSMENT</div>
            <div className="text-[#8ba4c4]">
              8x SAM batteries positioned along canyon ridgelines.
              SA-6, SA-10, SA-11, SA-15 systems. Altitude ceiling: 150-200m AGL.
              <span className="text-[#ff3333]"> Fly above the ridgeline and you will be engaged.</span>
            </div>
          </div>

          <div className="border-l-2 border-[#00e5ff]/30 pl-3">
            <div className="text-[#00e5ff] tracking-wider text-[10px] mb-1">COUNTERMEASURES</div>
            <div className="text-[#8ba4c4]">
              8x Chaff (Z key) — Radar missile defeat<br />
              8x Flares (X key) — IR missile defeat<br />
              Evasive maneuvers increase defeat probability by 15%
            </div>
          </div>

          <div className="border-l-2 border-[#00ff66]/30 pl-3">
            <div className="text-[#00ff66] tracking-wider text-[10px] mb-1">FLIGHT PLAN</div>
            <div className="text-[#8ba4c4]">
              Carrier launch → Transit to canyon → Low-alt canyon run →
              Target strike (SPACE to drop) → Egress → RTB to carrier
            </div>
          </div>
        </div>

        {/* Controls summary */}
        <div className="mt-4 pt-3 border-t border-[#1a3a5c]">
          <div className="grid grid-cols-2 gap-2 text-[10px] font-mono text-[#4a6a8a]">
            <div>W/S — Throttle / Brake</div>
            <div>A/D — Turn Left / Right</div>
            <div>Q/E — Roll Left / Right</div>
            <div>Up/Down — Climb / Descend</div>
            <div>Z — Deploy Chaff</div>
            <div>X — Deploy Flares</div>
            <div>SPACE — Drop Bomb</div>
          </div>
        </div>

        {/* START BUTTON */}
        <button
          onClick={() => setDismissed(true)}
          className="w-full mt-6 py-4 bg-[#ff3333]/10 border-2 border-[#ff3333]/50 text-[#ff3333]
                     text-sm tracking-[0.4em] font-mono font-bold rounded-sm
                     hover:bg-[#ff3333]/20 hover:border-[#ff3333]/80 hover:text-white
                     transition-all duration-200 cursor-pointer pointer-events-auto"
          style={{ textShadow: '0 0 10px rgba(255, 51, 51, 0.3)' }}
        >
          COMMENCE OPERATIONS
        </button>
      </div>
    </div>
  );
}
