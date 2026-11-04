import { BuilderHUD } from '../features/builder/components/BuilderHUD';

interface BuilderModeUIProps {
  onExecuteMission?: () => void;
}

export function BuilderModeUI({ onExecuteMission }: BuilderModeUIProps) {
  return (
    <>
      <BuilderHUD onExecuteMission={onExecuteMission} />
    </>
  );
}
