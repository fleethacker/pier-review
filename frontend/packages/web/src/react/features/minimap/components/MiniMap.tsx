import { useState, useRef, useCallback, useEffect } from 'react';
import Map, { Marker, NavigationControl, type MapRef } from 'react-map-gl/mapbox';
import { useVehiclePosition } from '../hooks/useVehiclePosition';
import { useGameMethod } from '../../../hooks/useGameMethod';
import { getTokens } from '../../../../utils/tokenValidator';
import { MapIcon } from 'lucide-react';
import 'mapbox-gl/dist/mapbox-gl.css';

const MAPBOX_TOKEN = getTokens().mapbox;

interface SearchResult {
  id: string;
  place_name: string;
  center: [number, number];
}

export function MiniMap() {
  const [isVisible, setIsVisible] = useState(true);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isNorthUp, setIsNorthUp] = useState(true);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const position = useVehiclePosition();
  const { teleportTo } = useGameMethod();
  const mapRef = useRef<MapRef>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const debounceTimerRef = useRef<NodeJS.Timeout>();

  const handleToggleVisibility = useCallback(() => {
    setIsVisible(!isVisible);
  }, [isVisible]);

  const handleToggleExpanded = useCallback(() => {
    setIsExpanded(!isExpanded);
    // Trigger a resize after the CSS transition so Mapbox recalculates viewport
    setTimeout(() => {
      mapRef.current?.resize();
    }, 320);
  }, [isExpanded]);

  const handleToggleNorthUp = useCallback(() => {
    setIsNorthUp(!isNorthUp);
  }, [isNorthUp]);

  const handleToggleSearch = useCallback(() => {
    setIsSearchOpen(!isSearchOpen);
    if (!isSearchOpen) {
      setTimeout(() => searchInputRef.current?.focus(), 100);
    } else {
      setSearchQuery('');
      setSearchResults([]);
    }
  }, [isSearchOpen]);

  const fetchSearchResults = useCallback(async (query: string) => {
    if (query.length < 3) {
      setSearchResults([]);
      return;
    }

    setIsSearching(true);
    try {
      const response = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(query)}.json?access_token=${MAPBOX_TOKEN}&limit=5`
      );
      const data = await response.json();
      setSearchResults(data.features || []);
    } catch (error) {
      console.error('Search error:', error);
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const query = e.target.value;
    setSearchQuery(query);

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = setTimeout(() => {
      fetchSearchResults(query);
    }, 300);
  }, [fetchSearchResults]);

  const handleSelectLocation = useCallback((result: SearchResult) => {
    const [longitude, latitude] = result.center;
    
    teleportTo(longitude, latitude, 500, 0);

    setSearchQuery('');
    setSearchResults([]);
    setIsSearchOpen(false);
  }, [teleportTo]);

  const handleSearchSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (searchResults.length > 0) {
      handleSelectLocation(searchResults[0]);
    }
  }, [searchResults, handleSelectLocation]);

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const mapBearing = isNorthUp ? 0 : -position.heading;
  const size = isExpanded
    ? 'w-[280px] h-[280px] md:w-[500px] md:h-[500px]'
    : 'w-[160px] h-[160px] md:w-[280px] md:h-[280px]';

  return (
    <>
      {!isVisible && (
        <button
          onClick={handleToggleVisibility}
          className="fixed bottom-[72px] right-8 z-50 w-12 h-12 flex items-center justify-center
                     glass-panel hover:bg-mil-border/30 transition-all duration-300
                     text-mil-dim hover:text-white text-lg group"
          title="Show Map"
        >
          <MapIcon size={18} className="group-hover:scale-110 transition-transform" />
        </button>
      )}

      {isVisible && (
        <div className={`fixed bottom-[72px] right-8 z-50 ${size} transition-all duration-300`}>
          <div className="relative w-full h-full glass-panel overflow-hidden rounded-lg shadow-2xl">
            {/* Header */}
            <div className="absolute top-0 left-0 right-0 z-20 bg-mil-panel/95 border-b border-mil-border">
              <div className="relative flex items-center justify-between h-10 px-2">
                {/* Left side - Search */}
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={handleToggleSearch}
                    className="w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 
                             rounded-md transition-all duration-200 text-mil-text hover:text-white"
                    title="Search location"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="11" cy="11" r="8"/>
                      <path d="m21 21-4.35-4.35"/>
                    </svg>
                  </button>

                  {/* Coordinates display (only when search is closed) */}
                  {!isSearchOpen && (
                    <div className="text-[10px] text-mil-dim font-mono">
                      {position.latitude.toFixed(4)}°, {position.longitude.toFixed(4)}°
                    </div>
                  )}
                </div>

                {/* Right side - Controls */}
                <div className="flex items-center gap-1.5">
                  {/* Expand/Collapse */}
                  <button
                    onClick={handleToggleExpanded}
                    className="w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 
                             rounded-md transition-all duration-200 text-mil-text hover:text-white"
                    title={isExpanded ? 'Collapse' : 'Expand'}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      {isExpanded ? (
                        <path d="M4 14h6m0 0v6m0-6l-7 7M20 10h-6m0 0V4m0 6l7-7"/>
                      ) : (
                        <path d="M15 3h6m0 0v6m0-6l-7 7M9 21H3m0 0v-6m0 6l7-7"/>
                      )}
                    </svg>
                  </button>
                </div>

                {/* Search input overlay */}
                <div 
                  className={`absolute left-0 right-0 top-0 h-10 bg-black/70 backdrop-blur-md border-b border-mil-border
                            transition-all duration-300 ease-out ${
                              isSearchOpen ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-full pointer-events-none'
                            }`}
                  style={{ zIndex: 30 }}
                >
                  <form onSubmit={handleSearchSubmit} className="h-full px-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleToggleSearch}
                      className="w-8 h-8 flex items-center justify-center hover:bg-mil-border/30 
                               rounded-md transition-colors text-mil-text hover:text-white flex-shrink-0"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M19 12H5M5 12l7 7M5 12l7-7"/>
                      </svg>
                    </button>
                    <input
                      ref={searchInputRef}
                      type="text"
                      value={searchQuery}
                      onChange={handleSearchChange}
                      onKeyDown={(e) => e.stopPropagation()}
                      onKeyUp={(e) => e.stopPropagation()}
                      onKeyPress={(e) => e.stopPropagation()}
                      placeholder="ENTER COORDINATES..."
                      className="flex-1 h-7 px-3 bg-mil-panel border border-mil-border rounded-sm
                               text-mil-cyan text-xs font-mono tracking-wider placeholder:text-mil-dim
                               focus:outline-none focus:border-mil-cyan/40 focus:bg-mil-panel/80
                               transition-all duration-200"
                    />
                  </form>
                </div>
              </div>

              {/* Search Results Dropdown */}
              {isSearchOpen && searchResults.length > 0 && (
                <div className="absolute top-10 left-0 right-0 bg-[#0a1628]/95 border border-mil-border
                              max-h-60 overflow-y-auto z-20 rounded-sm">
                  {searchResults.map((result) => (
                    <button
                      key={result.id}
                      onClick={() => handleSelectLocation(result)}
                      className="w-full px-3 py-2 text-left hover:bg-mil-cyan/10 transition-colors
                               border-b border-mil-border last:border-b-0"
                    >
                      <div className="text-[10px] text-mil-text font-mono tracking-wide">{result.place_name}</div>
                    </button>
                  ))}
                </div>
              )}

              {/* Search loading indicator */}
              {isSearchOpen && isSearching && (
                <div className="absolute top-10 left-0 right-0 bg-[#0a1628]/95 border border-mil-border
                              px-3 py-2 z-20 rounded-sm">
                  <div className="text-[10px] text-mil-amber font-mono tracking-wider animate-pulse">SEARCHING...</div>
                </div>
              )}
            </div>

            {/* Map */}
            <Map
              ref={mapRef}
              mapboxAccessToken={MAPBOX_TOKEN}
              initialViewState={{
                longitude: position.longitude,
                latitude: position.latitude,
                zoom: isExpanded ? 14 : 13,
                bearing: mapBearing,
              }}
              {...(!isExpanded && {
                longitude: position.longitude,
                latitude: position.latitude,
                zoom: 13,
                bearing: mapBearing,
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
              {/* Vehicle Marker */}
              <Marker
                longitude={position.longitude}
                latitude={position.latitude}
                anchor="center"
              >
                <div className="relative">
                  <div className="w-3 h-3 rounded-full bg-mil-cyan border-2 border-white shadow-lg
                                ring-4 ring-mil-cyan/30 animate-pulse" />
                </div>
              </Marker>

              {/* Navigation Controls (only when expanded) */}
              {isExpanded && (
                <NavigationControl position="bottom-right" showCompass={false} />
              )}
            </Map>

            {/* Compass - Bottom Left */}
            <div className="absolute bottom-10 left-2 z-10">
              <button
                onClick={handleToggleNorthUp}
                className="relative w-10 h-10 rounded-sm bg-[#0a1628]/90 border border-mil-border
                         hover:bg-mil-border/30 transition-all duration-200 flex items-center justify-center group"
                title={isNorthUp ? 'North Up' : 'Heading Up'}
              >
                <div
                  className="transition-transform duration-300"
                  style={{ transform: `rotate(${-mapBearing}deg)` }}
                >
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                    <path d="M12 4 L15 12 L12 10 L9 12 Z" fill="#00e5ff" className="group-hover:fill-white transition-colors"/>
                    <path d="M12 20 L9 12 L12 14 L15 12 Z" fill="#1a3a5c"/>
                  </svg>
                </div>
              </button>
            </div>

            {/* Bottom info bar */}
            <div className="absolute bottom-0 left-0 right-0 z-10 h-8 bg-mil-panel/95 
                          border-t border-mil-border flex items-center justify-between px-3">
              <div className="text-[11px] text-mil-dim font-mono">
                ALT {Math.round(position.altitude)}m
              </div>
              <div className="text-[11px] text-mil-dim font-mono">
                HDG {((Math.round(position.heading)) % 360)}°
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

