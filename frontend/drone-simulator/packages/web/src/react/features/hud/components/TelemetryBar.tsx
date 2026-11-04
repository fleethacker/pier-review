import { useVehicleState } from '../hooks/useVehicleState';
import { useVehiclePosition } from '../../minimap/hooks/useVehiclePosition';

function HeadingTape({ heading }: { heading: number }) {
  const cardinals: Record<number, string> = {
    0: 'N', 45: 'NE', 90: 'E', 135: 'SE',
    180: 'S', 225: 'SW', 270: 'W', 315: 'NW',
  };

  const marks: JSX.Element[] = [];
  const width = 400;
  const degsVisible = 120;
  const pxPerDeg = width / degsVisible;

  // Iterate over absolute compass degrees (every 5°) that fall within view
  // This ensures we never skip a cardinal/major tick
  const startDeg = Math.floor((heading - degsVisible / 2 - 5) / 5) * 5;
  const endDeg = Math.ceil((heading + degsVisible / 2 + 5) / 5) * 5;

  for (let deg = startDeg; deg <= endDeg; deg += 5) {
    // Wrap to 0-359
    const actualDeg = ((deg % 360) + 360) % 360;

    // Pixel offset: how far this degree is from current heading, mapped to pixels
    let diff = deg - heading;
    const offset = diff * pxPerDeg + width / 2;

    if (offset < -20 || offset > width + 20) continue;

    const isCardinal = actualDeg % 45 === 0;
    const isMajor = actualDeg % 10 === 0;

    marks.push(
      <g key={deg}>
        <line
          x1={offset} y1={isCardinal ? 2 : isMajor ? 6 : 10}
          x2={offset} y2={16}
          stroke={isCardinal ? '#00e5ff' : '#4a6a8a'}
          strokeWidth={isCardinal ? 1.5 : 0.5}
        />
        {isCardinal && cardinals[actualDeg] !== undefined && (
          <text
            x={offset} y={26}
            textAnchor="middle"
            fill="#00e5ff"
            fontSize={10}
            fontFamily="monospace"
            fontWeight="bold"
          >
            {cardinals[actualDeg]}
          </text>
        )}
        {isMajor && !isCardinal && (
          <text
            x={offset} y={26}
            textAnchor="middle"
            fill="#4a6a8a"
            fontSize={8}
            fontFamily="monospace"
          >
            {actualDeg}
          </text>
        )}
      </g>
    );
  }

  return (
    <div className="relative overflow-hidden" style={{ width: `${width}px`, height: '30px' }}>
      <svg width={width} height={30} className="block">
        {marks}
        {/* Center marker */}
        <polygon points={`${width / 2 - 4},0 ${width / 2 + 4},0 ${width / 2},6`} fill="#ffc107" />
      </svg>
    </div>
  );
}

function DataCell({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[60px]">
      <span className="mil-label">{label}</span>
      <div className="flex items-baseline gap-0.5">
        <span className="text-sm mil-value text-glow-subtle">{value}</span>
        {unit && <span className="text-[8px] text-mil-dim">{unit}</span>}
      </div>
    </div>
  );
}

export function TelemetryBar() {
  const { speed, heading, pitch, roll } = useVehicleState();
  const position = useVehiclePosition();

  const headingDeg = ((Math.round(heading * 180 / Math.PI) % 360) + 360) % 360;
  const pitchDeg = Math.round(pitch * 180 / Math.PI);
  const rollDeg = Math.round(roll * 180 / Math.PI);

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 pointer-events-none">
      <div className="h-14 bg-[#0a1628] border-t border-mil-border flex items-center justify-between px-6">
        {/* Left: Position data */}
        <div className="flex items-center gap-4">
          <DataCell label="LAT" value={position.latitude.toFixed(4)} />
          <div className="w-px h-6 bg-mil-border" />
          <DataCell label="LON" value={position.longitude.toFixed(4)} />
          <div className="w-px h-6 bg-mil-border" />
          <DataCell label="ALT" value={Math.round(position.altitude)} unit="m" />
        </div>

        {/* Center: Speed + heading tape */}
        <div className="flex flex-col items-center gap-0.5">
          <HeadingTape heading={headingDeg} />
          <div className="flex items-center gap-3">
            <span className={`text-lg mil-value ${speed > 146 ? 'text-[#ffc107]' : 'text-glow'}`}>{Math.round(speed * 3.6)}</span>
            <span className="text-[9px] text-mil-dim uppercase tracking-widest">km/h</span>
            {speed > 146 && <span className="text-[8px] text-[#ffc107] tracking-wider animate-pulse">SIM SPEED</span>}
          </div>
        </div>

        {/* Right: Attitude data */}
        <div className="flex items-center gap-4">
          <DataCell label="HDG" value={`${headingDeg}`} unit="°" />
          <div className="w-px h-6 bg-mil-border" />
          <DataCell label="PITCH" value={`${pitchDeg}`} unit="°" />
          <div className="w-px h-6 bg-mil-border" />
          <DataCell label="ROLL" value={`${rollDeg}`} unit="°" />
        </div>
      </div>
    </div>
  );
}
