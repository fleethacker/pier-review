import { ControlsPanel } from '../features/controls/components/ControlsPanel';
import { BottomRightPanel } from '../features/detection/components/BottomRightPanel';
import { StatusBar } from '../features/hud/components/StatusBar';
import { Reticle } from '../features/hud/components/Reticle';
import type { Detection } from '../features/detection/hooks/useObjectDetection';

interface PlayModeUIProps {
  onDetections?: (detections: Detection[], lat: number, lon: number, alt: number) => void;
}

export function PlayModeUI({ onDetections }: PlayModeUIProps) {
  return (
    <>
      <StatusBar />
      <Reticle />
      <ControlsPanel />
      <BottomRightPanel onDetections={onDetections} />
    </>
  );
}
