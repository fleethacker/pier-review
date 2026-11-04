export function Reticle() {
  return (
    <div className="fixed inset-0 z-30 pointer-events-none flex items-center justify-center">
      <svg width="200" height="200" viewBox="0 0 200 200" fill="none" className="opacity-40">
        {/* Outer ring */}
        <circle cx="100" cy="100" r="80" stroke="#00e5ff" strokeWidth="0.5" strokeDasharray="4 4" />
        {/* Inner ring */}
        <circle cx="100" cy="100" r="40" stroke="#00e5ff" strokeWidth="0.5" strokeDasharray="2 4" />

        {/* Crosshair lines */}
        <line x1="100" y1="10" x2="100" y2="55" stroke="#00e5ff" strokeWidth="0.8" />
        <line x1="100" y1="145" x2="100" y2="190" stroke="#00e5ff" strokeWidth="0.8" />
        <line x1="10" y1="100" x2="55" y2="100" stroke="#00e5ff" strokeWidth="0.8" />
        <line x1="145" y1="100" x2="190" y2="100" stroke="#00e5ff" strokeWidth="0.8" />

        {/* Center dot */}
        <circle cx="100" cy="100" r="2" fill="#00e5ff" />

        {/* Corner brackets */}
        <path d="M60 60 L60 70 M60 60 L70 60" stroke="#00e5ff" strokeWidth="1" />
        <path d="M140 60 L140 70 M140 60 L130 60" stroke="#00e5ff" strokeWidth="1" />
        <path d="M60 140 L60 130 M60 140 L70 140" stroke="#00e5ff" strokeWidth="1" />
        <path d="M140 140 L140 130 M140 140 L130 140" stroke="#00e5ff" strokeWidth="1" />

        {/* Tick marks on crosshairs */}
        <line x1="95" y1="70" x2="105" y2="70" stroke="#00e5ff" strokeWidth="0.5" />
        <line x1="95" y1="130" x2="105" y2="130" stroke="#00e5ff" strokeWidth="0.5" />
        <line x1="70" y1="95" x2="70" y2="105" stroke="#00e5ff" strokeWidth="0.5" />
        <line x1="130" y1="95" x2="130" y2="105" stroke="#00e5ff" strokeWidth="0.5" />
      </svg>
    </div>
  );
}
