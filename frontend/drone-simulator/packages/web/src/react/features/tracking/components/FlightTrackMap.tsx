import { useState, useRef, useCallback, useMemo } from 'react';
import Map, { Marker, Source, Layer, type MapRef } from 'react-map-gl/mapbox';
import { useFlightPath } from '../hooks/useFlightPath';
import { getTokens } from '../../../../utils/tokenValidator';
import 'mapbox-gl/dist/mapbox-gl.css';

const MAPBOX_TOKEN = getTokens().mapbox;

export function FlightTrackMap() {
  const [isExpanded, setIsExpanded] = useState(false);
  const { path, clearPath, totalDistance, flightDuration, currentPosition } = useFlightPath();
  const mapRef = useRef<MapRef>(null);

  const size = isExpanded
    ? 'w-[280px] h-[280px] md:w-[500px] md:h-[500px]'
    : 'w-[160px] h-[160px] md:w-[280px] md:h-[280px]';

  const handleToggleExpanded = useCallback(() => {
    setIsExpanded(!isExpanded);
    setTimeout(() => mapRef.current?.resize(), 320);
  }, [isExpanded]);

  const mins = String(Math.floor(flightDuration / 60)).padStart(2, '0');
  const secs = String(flightDuration % 60).padStart(2, '0');

  const geojson = useMemo(() => ({
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'LineString' as const,
      coordinates: path.map((p) => [p.lon, p.lat]),
    },
  }), [path]);

  const startPoint = path.length > 0 ? path[0] : null;

  return (
    <div className={`${size} transition-all duration-300`}>
      <div className="relative w-full h-full glass-panel mil-brackets overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-20 bg-mil-panel/90 border-b border-mil-border">
          <div className="flex items-center justify-between h-10 px-2">
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-mil-green animate-pulse" />
              <span className="mil-label">FLIGHT TRACK</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-mil-text font-mono">
                {totalDistance.toFixed(1)} km
              </span>
              <button
                onClick={clearPath}
                className="w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 rounded-sm transition-colors text-mil-dim hover:text-mil-cyan"
                title="Clear path"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
                </svg>
              </button>
              <button
                onClick={handleToggleExpanded}
                className="w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 rounded-sm transition-colors text-mil-dim hover:text-mil-cyan"
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

        {/* Map */}
        <Map
          ref={mapRef}
          mapboxAccessToken={MAPBOX_TOKEN}
          initialViewState={{
            longitude: currentPosition.longitude,
            latitude: currentPosition.latitude,
            zoom: isExpanded ? 14 : 13,
          }}
          {...(!isExpanded && {
            longitude: currentPosition.longitude,
            latitude: currentPosition.latitude,
            zoom: 13,
          })}
          style={{ width: '100%', height: '100%' }}
          mapStyle="mapbox://styles/mapbox/dark-v11"
          attributionControl={false}
          dragPan={isExpanded}
          scrollZoom={isExpanded}
          doubleClickZoom={false}
          touchZoomRotate={isExpanded}
          interactive={isExpanded}
        >
          {/* Flight path line */}
          {path.length >= 2 && (
            <Source id="flight-path" type="geojson" data={geojson}>
              {/* Glow layer */}
              <Layer
                id="flight-path-glow"
                type="line"
                paint={{
                  'line-color': '#00e676',
                  'line-width': 6,
                  'line-opacity': 0.15,
                  'line-blur': 4,
                }}
              />
              {/* Main line */}
              <Layer
                id="flight-path-line"
                type="line"
                paint={{
                  'line-color': '#00e676',
                  'line-width': 2,
                  'line-opacity': 0.8,
                }}
              />
            </Source>
          )}

          {/* Start position marker */}
          {startPoint && (
            <Marker longitude={startPoint.lon} latitude={startPoint.lat} anchor="center">
              <div className="w-3 h-3 rounded-full bg-mil-amber border border-mil-amber/50 shadow-lg" />
            </Marker>
          )}

          {/* Current position marker */}
          <Marker
            longitude={currentPosition.longitude}
            latitude={currentPosition.latitude}
            anchor="center"
          >
            <div className="relative">
              <div className="w-3 h-3 rounded-full bg-mil-cyan border-2 border-white shadow-lg ring-4 ring-mil-cyan/30 animate-pulse" />
            </div>
          </Marker>
        </Map>

        {/* Bottom info bar */}
        <div className="absolute bottom-0 left-0 right-0 z-10 h-8 bg-mil-panel/90 border-t border-mil-border flex items-center justify-between px-3">
          <div className="text-[10px] text-mil-dim font-mono">
            T+ {mins}:{secs}
          </div>
          <div className="text-[10px] text-mil-dim font-mono">
            {path.length} PTS
          </div>
        </div>
      </div>
    </div>
  );
}
