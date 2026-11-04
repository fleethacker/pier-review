import { useState, useEffect } from 'react';

export function StatusBar() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const hours = String(Math.floor(elapsed / 3600)).padStart(2, '0');
  const mins = String(Math.floor((elapsed % 3600) / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');

  return (
    <div className="fixed top-0 left-0 right-0 z-50 pointer-events-auto">
      <div className="h-8 bg-[#0a1628] border-b border-mil-border flex items-center justify-between px-4">
        {/* Left: Mission info */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => window.location.reload()}
            className="mil-label text-mil-amber hover:text-white transition-colors cursor-pointer"
            title="Return to mission select"
          >
            DRONE OPS
          </button>
          <span className="text-[10px] text-mil-text font-mono">
            T+ {hours}:{mins}:{secs}
          </span>
        </div>

        {/* Center: Camera status */}
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-mil-red animate-blink" />
          <span className="text-[10px] text-mil-text font-mono tracking-wider">CAM LIVE</span>
          <span className="text-[10px] text-mil-dim">|</span>
          <span className="text-[10px] text-mil-dim font-mono">ISR ACTIVE</span>
        </div>

        {/* Right: System status */}
        <div className="flex items-center gap-4">
          <span className="text-[10px] text-mil-text font-mono">X-47B</span>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-mil-dim">SYS</span>
            <div className="w-1.5 h-1.5 rounded-full bg-mil-green" />
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-mil-dim">LINK</span>
            <div className="w-1.5 h-1.5 rounded-full bg-mil-green" />
          </div>
        </div>
      </div>
    </div>
  );
}
