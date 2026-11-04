import { useState, useRef, useCallback, useEffect } from 'react';
import { Search } from 'lucide-react';
import { type BaseLocation } from '../../baseLocation';
import { getTokens } from '../../utils/tokenValidator';

interface LocationPickerProps {
  onSelect: (location: BaseLocation) => void;
}

interface GeoResult {
  id: string;
  place_name: string;
  center: [number, number]; // [lng, lat]
}

export function LocationPicker({ onSelect }: LocationPickerProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GeoResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const [isMaverick, setIsMaverick] = useState(false);

  const search = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults([]);
      setShowResults(false);
      setIsMaverick(false);
      return;
    }

    // Easter egg: "maverick" triggers classified mission
    if (q.toLowerCase().includes('maverick')) {
      setIsMaverick(true);
      setResults([]);
      setShowResults(true);
      setIsSearching(false);
      return;
    }
    setIsMaverick(false);

    setIsSearching(true);
    try {
      const token = getTokens().mapbox;
      const res = await fetch(
        `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(q)}.json?access_token=${token}&limit=5&types=place,poi,address,neighborhood,locality`
      );
      const data = await res.json();
      setResults(data.features || []);
      setShowResults(true);
    } catch {
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(val), 300);
  };

  const handleSelect = (result: GeoResult) => {
    const [lng, lat] = result.center;
    onSelect({
      id: result.id,
      name: result.place_name.split(',')[0],
      country: result.place_name.split(',').slice(-1)[0]?.trim() || '',
      longitude: lng,
      latitude: lat,
      altitude: 200,
      heading: 0,
    });
  };

  const handleMaverickSelect = () => {
    onSelect({
      id: 'maverick',
      name: 'CLASSIFIED MISSION: MAVERICK',
      country: 'USA',
      longitude: -119.30,
      latitude: 34.02,
      altitude: 18,
      heading: 315,
      missionId: 'maverick',
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isMaverick) {
      handleMaverickSelect();
      return;
    }
    if (results.length > 0) {
      handleSelect(results[0]);
    }
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div className="fixed inset-0 bg-[#0a1628] flex flex-col items-center justify-center p-4 z-[9999]">
      {/* Subtle grid background */}
      <div className="absolute inset-0 opacity-5"
        style={{
          backgroundImage: 'linear-gradient(rgba(0,229,255,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(0,229,255,0.3) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      <div className="relative w-full max-w-xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="text-[10px] tracking-[0.4em] text-[#ffc107] font-mono mb-2">CLASSIFIED // DRONE OPS</div>
          <h1 className="text-xl font-mono font-bold text-[#00e5ff] tracking-wider mb-1"
            style={{ textShadow: '0 0 20px rgba(0, 229, 255, 0.3)' }}>
            SELECT AREA OF OPERATIONS
          </h1>
          <p className="text-[11px] text-[#4a6a8a] font-mono tracking-wider">X-47B UCAV // MISSION PLANNING</p>
        </div>

        <form onSubmit={handleSubmit} className="relative">
          {/* Corner brackets on search container */}
          <div className="relative">
            {/* Top-left bracket */}
            <div className="absolute -top-1 -left-1 w-4 h-4 border-t-2 border-l-2 border-[#00e5ff]/40 pointer-events-none" />
            {/* Bottom-right bracket */}
            <div className="absolute -bottom-1 -right-1 w-4 h-4 border-b-2 border-r-2 border-[#00e5ff]/40 pointer-events-none" />

            <Search
              size={18}
              className={`absolute left-5 top-1/2 -translate-y-1/2 transition-colors ${
                isSearching ? 'text-[#00e5ff] animate-pulse' : 'text-[#4a6a8a]'
              }`}
            />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={handleChange}
              placeholder="ENTER TARGET LOCATION..."
              className="w-full pl-14 pr-6 py-4 bg-[#0d1f3c]/80 border border-[#1a3a5c] rounded-sm
                       text-[#00e5ff] text-sm font-mono tracking-wider placeholder:text-[#4a6a8a]
                       focus:outline-none focus:border-[#00e5ff]/40 focus:bg-[#0d1f3c]
                       transition-all duration-200"
              style={{ boxShadow: '0 4px 20px rgba(0, 10, 30, 0.8), inset 0 1px 0 rgba(0, 229, 255, 0.05)' }}
            />
          </div>

          {/* Maverick mission result */}
          {showResults && isMaverick && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-[#1a0a0a]
                          border border-[#ff3333]/50 rounded-sm overflow-hidden z-10"
              style={{ boxShadow: '0 8px 30px rgba(255, 0, 0, 0.2)' }}>
              <button
                type="button"
                onClick={handleMaverickSelect}
                className="w-full px-5 py-4 text-left hover:bg-[#ff3333]/10 transition-colors group"
              >
                <div className="flex items-center gap-3">
                  <span className="text-[10px] text-[#ff3333] font-mono tracking-[0.3em] animate-pulse">
                    CLASSIFIED
                  </span>
                  <span className="text-sm text-[#ff6666] font-mono tracking-wide font-bold group-hover:text-white transition-colors">
                    MISSION: MAVERICK
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-[#ff3333]/60 font-mono tracking-wider">
                  CARRIER LAUNCH // CANYON RUN // SAM EVASION // TOP GUN PROTOCOL
                </div>
              </button>
            </div>
          )}

          {/* Results dropdown */}
          {showResults && !isMaverick && results.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-[#0a1628]
                          border border-[#1a3a5c] rounded-sm overflow-hidden z-10"
              style={{ boxShadow: '0 8px 30px rgba(0, 10, 30, 0.9)' }}>
              {results.map((result, i) => (
                <button
                  key={result.id}
                  type="button"
                  onClick={() => handleSelect(result)}
                  className="w-full px-5 py-3 text-left hover:bg-[#00e5ff]/10 transition-colors
                           border-b border-[#1a3a5c]/50 last:border-0 flex items-center gap-3 group"
                >
                  <span className="text-[10px] text-[#00e5ff] font-mono w-6 flex-shrink-0">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="text-xs text-[#8ba4c4] font-mono tracking-wide group-hover:text-white transition-colors">
                    {result.place_name}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Searching indicator */}
          {isSearching && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-[#0a1628]
                          border border-[#1a3a5c] rounded-sm px-5 py-3 z-10">
              <span className="text-[10px] text-[#ffc107] font-mono tracking-wider animate-pulse">
                QUERYING DATABASE...
              </span>
            </div>
          )}
        </form>

        {/* Hint */}
        <div className="text-center mt-6">
          <p className="text-[10px] text-[#4a6a8a] font-mono tracking-wider">
            ENTER CITY, LANDMARK, OR COORDINATES TO DEPLOY
          </p>
        </div>
      </div>
    </div>
  );
}
