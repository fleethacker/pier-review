import { useState } from 'react';
import { type ReactNode } from 'react';
import { Button } from './Button';
import { isMobileDevice } from '../utils/mobileDetect';
import { MoveHorizontal, MoveVertical, SlidersHorizontal } from 'lucide-react';

export function IntroScreen() {
  const [isVisible, setIsVisible] = useState(true);
  const isMobile = isMobileDevice();

  if (!isVisible) return null;

  return (
    <div className="fixed inset-0 z-[180] bg-black/80 backdrop-blur-sm flex items-center justify-center animate-fade-in">
      <div className="max-w-2xl w-full mx-4">
        <div className="glass-panel mil-brackets p-8 space-y-6">
          {/* Header */}
          <div className="text-center space-y-2">
            <div className="mil-label text-mil-amber tracking-[0.3em] mb-1">CLASSIFIED</div>
            <h1 className="text-2xl font-bold text-mil-cyan text-glow tracking-wider">
              MISSION BRIEFING
            </h1>
            <p className="text-mil-dim text-xs font-mono">
              {isMobile ? 'Touch control interface initialized' : 'X-47B UCAV // OPERATIONAL READINESS CHECK'}
            </p>
          </div>

          {isMobile ? <MobileControls /> : <DesktopControls />}

          {/* Quick Tips */}
          <div className="bg-mil-panel/50 border border-mil-border rounded-sm p-4">
            <h3 className="mil-label text-mil-amber mb-2">OPERATIONAL NOTES</h3>
            <ul className="space-y-1.5 text-xs text-mil-dim font-mono">
              {isMobile ? (
                <>
                  <li className="flex items-start gap-2">
                    <span className="text-mil-cyan mt-0.5">&gt;</span>
                    <span>Touch controls respond to finger movements</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-mil-cyan mt-0.5">&gt;</span>
                    <span>Maintain altitude to avoid terrain collision</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-mil-cyan mt-0.5">&gt;</span>
                    <span>Haptic feedback active during flight ops</span>
                  </li>
                </>
              ) : (
                <>
                  <li className="flex items-start gap-2">
                    <span className="text-mil-cyan mt-0.5">&gt;</span>
                    <span>Use map search to navigate to area of operations</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-mil-cyan mt-0.5">&gt;</span>
                    <span>Maintain altitude to avoid terrain collision</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-mil-cyan mt-0.5">&gt;</span>
                    <span>Press <strong className="text-mil-cyan">R</strong> to reinitialize after system failure</span>
                  </li>
                </>
              )}
            </ul>
          </div>

          {/* Start Button */}
          <div className="flex justify-center pt-2">
            <Button
              onClick={() => setIsVisible(false)}
              variant="primary"
              size="lg"
              className="px-12 tracking-[0.15em]"
            >
              COMMENCE OPERATIONS
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileControls() {
  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <h3 className="mil-label">CONTROL INTERFACE</h3>
        <div className="space-y-2.5">
          <TouchControlRow
            icon={<MoveHorizontal size={24} className="text-mil-dim" />}
            action="Swipe Left/Right"
            description="Roll drone (banking)"
          />
          <TouchControlRow
            icon={<MoveVertical size={24} className="text-mil-dim" />}
            action="Swipe Up/Down"
            description="Climb/Descend"
          />
          <TouchControlRow
            icon={<SlidersHorizontal size={24} className="text-mil-dim" />}
            action="Right Slider"
            description="Throttle control"
          />
        </div>
      </div>
    </div>
  );
}

function DesktopControls() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="space-y-3">
        <h3 className="mil-label">FLIGHT CONTROLS</h3>
        <div className="space-y-2">
          <ControlRow keys={['W']} action="Throttle Up" />
          <ControlRow keys={['S']} action="Throttle Down" />
          <ControlRow keys={['A', 'D', '\u2190', '\u2192']} action="Roll / Yaw" />
        </div>
      </div>

      <div className="space-y-3">
        <h3 className="mil-label">SYSTEM CONTROLS</h3>
        <div className="space-y-2">
          <ControlRow keys={['?']} action="Controls Reference" />
          <ControlRow keys={['~']} action="Diagnostics Panel" />
        </div>
      </div>
    </div>
  );
}

interface ControlRowProps {
  keys: string[];
  action: string;
}

function ControlRow({ keys, action }: ControlRowProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex gap-1.5">
        {keys.map((key) => (
          <kbd
            key={key}
            className="px-2 py-1 text-[10px] font-mono font-medium text-mil-cyan bg-mil-panel border border-mil-border rounded-sm min-w-[24px] text-center"
          >
            {key}
          </kbd>
        ))}
      </div>
      <span className="text-xs text-mil-dim font-mono flex-1">{action}</span>
    </div>
  );
}

interface TouchControlRowProps {
  icon: ReactNode;
  action: string;
  description: string;
}

function TouchControlRow({ icon, action, description }: TouchControlRowProps) {
  return (
    <div className="flex items-start gap-3 bg-mil-panel/50 border border-mil-border rounded-sm p-3">
      <div className="flex-shrink-0 w-6 h-6 flex items-center justify-center">{icon}</div>
      <div className="flex-1 space-y-0.5">
        <div className="text-sm font-mono font-medium text-mil-text">{action}</div>
        <div className="text-xs text-mil-dim font-mono">{description}</div>
      </div>
    </div>
  );
}
