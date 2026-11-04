import { useState, useRef, useEffect } from 'react';
import { useGameMethod } from '../../../hooks/useGameMethod';
import { MapPin } from 'lucide-react';
import { LOCATIONS, type BaseLocation } from '../../../../baseLocation';

export type Location = BaseLocation;

export function LocationSelector() {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const { teleportTo } = useGameMethod();
  const dropdownRef = useRef<HTMLDivElement>(null);

  const filteredLocations = LOCATIONS.filter(
    loc =>
      loc.name.toLowerCase().includes(search.toLowerCase()) ||
      loc.country.toLowerCase().includes(search.toLowerCase())
  );

  const handleSelect = (location: Location) => {
    teleportTo(location.longitude, location.latitude, location.altitude, location.heading);
    setIsOpen(false);
    setSearch('');
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="glass-panel px-4 py-2.5 hover:bg-white/10 transition-all duration-300 group flex items-center gap-2"
        title="Teleport to Location"
      >
        <svg className="w-4 h-4 text-white/60 group-hover:text-white/90 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <span className="text-xs font-medium text-white/80 group-hover:text-white transition-colors">
          Teleport
        </span>
      </button>

      {isOpen && (
        <div className="absolute top-14 right-0 w-80 glass-panel animate-fade-in z-[60]">
          <div className="p-3 border-b border-white/5">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search locations..."
              className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder:text-white/40 focus:outline-none focus:border-future-primary transition-colors"
              autoFocus
            />
          </div>
          
          <div className="max-h-96 overflow-y-auto">
            {filteredLocations.length > 0 ? (
              filteredLocations.map((location) => (
                <button
                  key={location.id}
                  onClick={() => handleSelect(location)}
                  className="w-full px-4 py-3 text-left hover:bg-white/5 transition-colors border-b border-white/5 last:border-0 group"
                >
                  <div className="flex items-start gap-3">
                    <MapPin size={20} className="text-white/50 group-hover:text-future-primary transition-colors flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-white group-hover:text-future-primary transition-colors">
                        {location.name}
                      </div>
                      <div className="text-xs text-white/50 mt-0.5">
                        {location.country}
                      </div>
                    </div>
                  </div>
                </button>
              ))
            ) : (
              <div className="px-4 py-8 text-center text-sm text-white/40">
                No locations found
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}



