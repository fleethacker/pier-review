import { Button } from '../../../shared/components/Button';
import { Gauge, Scale, Gem, Flame } from 'lucide-react';

interface QualityPresetsProps {
  onApplyPreset: (preset: 'performance' | 'balanced' | 'quality' | 'ultra') => void;
}

export function QualityPresets({ onApplyPreset }: QualityPresetsProps) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-white/70 uppercase tracking-wider mb-2 font-medium">Quick Presets</div>
      <div className="grid grid-cols-2 gap-2">
        <Button
          onClick={() => onApplyPreset('performance')}
          variant="secondary"
          size="sm"
          className="text-xs"
          title="SSE: 32, No bloom, Low quality"
        >
          <Gauge size={12} className="inline mr-1" /> Performance
        </Button>
        <Button
          onClick={() => onApplyPreset('balanced')}
          variant="secondary"
          size="sm"
          className="text-xs"
          title="SSE: 16, Balanced settings"
        >
          <Scale size={12} className="inline mr-1" /> Balanced
        </Button>
        <Button
          onClick={() => onApplyPreset('quality')}
          variant="secondary"
          size="sm"
          className="text-xs"
          title="SSE: 8, High quality for driving"
        >
          <Gem size={12} className="inline mr-1" /> Quality
        </Button>
        <Button
          onClick={() => onApplyPreset('ultra')}
          variant="secondary"
          size="sm"
          className="text-xs"
          title="SSE: 4, Maximum quality (slow!)"
        >
          <Flame size={12} className="inline mr-1" /> Ultra
        </Button>
      </div>
    </div>
  );
}

