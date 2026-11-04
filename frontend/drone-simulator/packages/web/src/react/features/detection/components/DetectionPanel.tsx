import { useState, useEffect, useRef } from 'react';
import { useVehiclePosition } from '../../minimap/hooks/useVehiclePosition';
import { useVehicleState } from '../../hud/hooks/useVehicleState';
import { useGameMethod } from '../../../hooks/useGameMethod';
import { useObjectDetection, type Detection } from '../hooks/useObjectDetection';

const CLASS_COLORS: Record<string, string> = {
  'small vehicle': '#00e5ff',   // cyan
  'large vehicle': '#ffc107',   // amber
  'plane': '#ff1744',           // red
  'helicopter': '#ff1744',      // red
  'ship': '#7c4dff',            // purple
  'harbor': '#7c4dff',          // purple
  'bridge': '#ff9100',          // orange
  'storage tank': '#ff9100',    // orange
  'swimming pool': '#00e676',   // green
  'baseball diamond': '#00e676',// green
  'tennis court': '#00e676',    // green
  'basketball court': '#00e676',// green
  'soccer ball field': '#00e676',// green
  'ground track field': '#00e676',// green
  'roundabout': '#ff9100',      // orange
};

function getColor(cls: string): string {
  return CLASS_COLORS[cls] || '#00e5ff';
}

interface DetectionPanelProps {
  isActive: boolean;
  onDetections?: (detections: Detection[], lat: number, lon: number, alt: number) => void;
}

function BoundingBox({ det, isExpanded }: { det: Detection; isExpanded: boolean }) {
  const color = getColor(det.class);
  const labelSize = isExpanded ? 13 : 11;
  const labelH = isExpanded ? 20 : 16;
  const labelW = Math.max((det.class.length + 5) * (labelSize * 0.65), 50);
  const strokeW = isExpanded ? 2.5 : 2;

  return (
    <g style={{ transition: 'all 0.6s ease-out' }}>
      <rect
        x={det.bbox.x1}
        y={det.bbox.y1}
        width={det.bbox.x2 - det.bbox.x1}
        height={det.bbox.y2 - det.bbox.y1}
        fill={`${color}11`}
        stroke={color}
        strokeWidth={strokeW}
        rx={2}
        style={{ transition: 'all 0.6s ease-out' }}
      />
      <rect
        x={det.bbox.x1}
        y={det.bbox.y1 - labelH}
        width={labelW}
        height={labelH}
        fill={color}
        opacity={0.9}
        rx={2}
        style={{ transition: 'all 0.6s ease-out' }}
      />
      <text
        x={det.bbox.x1 + 4}
        y={det.bbox.y1 - labelH + labelSize}
        fill="white"
        fontSize={labelSize}
        fontFamily="monospace"
        fontWeight="bold"
        style={{ transition: 'all 0.6s ease-out' }}
      >
        {det.class.toUpperCase()} {Math.round(det.confidence * 100)}%
      </text>
    </g>
  );
}

export function DetectionPanel({ isActive, onDetections }: DetectionPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const position = useVehiclePosition();
  const { speed } = useVehicleState();
  const { getAGL } = useGameMethod();
  const {
    detections,
    imageUrl,
    imageWidth,
    imageHeight,
    isLoading,
    error,
    lastUpdated,
    triggerDetection,
  } = useObjectDetection({
    latitude: position.latitude,
    longitude: position.longitude,
    altitude: position.altitude,
    heading: position.heading,
    speed,
    getAGL,
    isActive,
  });

  // Report detections to parent for ISR tracking
  const lastReportedUpdate = useRef(0);
  useEffect(() => {
    if (onDetections && lastUpdated > 0 && lastUpdated !== lastReportedUpdate.current) {
      lastReportedUpdate.current = lastUpdated;
      onDetections(detections, position.latitude, position.longitude, position.altitude);
    }
  }, [lastUpdated, detections, onDetections, position.latitude, position.longitude, position.altitude]);

  // Track previous image for crossfade
  const [displayedImage, setDisplayedImage] = useState('');
  const [imageReady, setImageReady] = useState(false);

  useEffect(() => {
    if (!imageUrl || imageUrl === displayedImage) return;
    // Preload the new image, then swap
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      setDisplayedImage(imageUrl);
      setImageReady(true);
    };
    img.src = imageUrl;
  }, [imageUrl]);

  const [timeSince, setTimeSince] = useState<number | null>(null);
  useEffect(() => {
    if (!lastUpdated) return;
    const tick = () => setTimeSince(Math.round((Date.now() - lastUpdated) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  const size = isExpanded
    ? 'w-[280px] h-[280px] md:w-[500px] md:h-[500px]'
    : 'w-[160px] h-[160px] md:w-[280px] md:h-[280px]';

  return (
    <div className={`${size} transition-all duration-300`}>
      <div className="relative w-full h-full glass-panel overflow-hidden rounded-lg shadow-2xl">
        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-20 bg-mil-panel/95 border-b border-mil-border">
          <div className="flex items-center justify-between h-10 px-2">
            <div className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${isLoading ? 'bg-mil-amber animate-pulse' : error ? 'bg-mil-red' : 'bg-mil-green'}`} />
              <span className="mil-label">
                {isLoading && !displayedImage ? 'SCANNING' : error ? 'ERROR' : `ISR // ${detections.length} TGT`}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {/* Refresh */}
              <button
                onClick={triggerDetection}
                className={`w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 rounded-md transition-all duration-200 text-mil-text hover:text-white ${isLoading ? 'animate-spin' : ''}`}
                title="Refresh detection"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 11-2.2-5.9" />
                  <path d="M21 3v6h-6" />
                </svg>
              </button>
              {/* Expand/Collapse */}
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 rounded-md transition-all duration-200 text-mil-text hover:text-white"
                title={isExpanded ? 'Collapse' : 'Expand'}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  {isExpanded ? (
                    <path d="M4 14h6m0 0v6m0-6l-7 7M20 10h-6m0 0V4m0 6l7-7" />
                  ) : (
                    <path d="M15 3h6m0 0v6m0-6l-7 7M9 21H3m0 0v-6m0 6l7-7" />
                  )}
                </svg>
              </button>
            </div>
          </div>
        </div>

        {/* Satellite image + detections */}
        <div className="w-full h-full relative bg-black">
          {displayedImage ? (
            <>
              <img
                src={displayedImage}
                alt="Satellite view"
                className="w-full h-full object-cover transition-opacity duration-500"
                style={{ opacity: imageReady ? 1 : 0 }}
                crossOrigin="anonymous"
              />
              {/* Scanning line effect while loading */}
              {isLoading && (
                <div className="absolute inset-0 overflow-hidden pointer-events-none z-10">
                  <div
                    className="absolute left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-cyan-400 to-transparent opacity-60"
                    style={{
                      animation: 'scanline 2s ease-in-out infinite',
                    }}
                  />
                  <style>{`
                    @keyframes scanline {
                      0% { top: 0%; }
                      50% { top: 100%; }
                      100% { top: 0%; }
                    }
                  `}</style>
                </div>
              )}
              {imageWidth > 0 && imageHeight > 0 && (
                <svg
                  className="absolute inset-0 w-full h-full"
                  viewBox={`0 0 ${imageWidth} ${imageHeight}`}
                  preserveAspectRatio="none"
                >
                  {detections.map((det) => (
                    <BoundingBox key={det.id} det={det} isExpanded={isExpanded} />
                  ))}
                </svg>
              )}
            </>
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <div className="flex flex-col items-center gap-2">
                <div className="w-6 h-6 border-2 border-white/30 border-t-white/80 rounded-full animate-spin" />
                <span className="text-white/40 text-xs">
                  {error || 'Initializing...'}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Bottom info bar */}
        <div className="absolute bottom-0 left-0 right-0 z-10 h-8 bg-mil-panel/95 border-t border-mil-border flex items-center justify-between px-3">
          <div className="text-[11px] text-mil-dim font-mono">
            {position.latitude.toFixed(4)}, {position.longitude.toFixed(4)}
          </div>
          <div className="text-[11px] text-mil-dim font-mono">
            {timeSince !== null ? `${timeSince}s ago` : '--'}
          </div>
        </div>
      </div>
    </div>
  );
}
