import { createRoot } from 'react-dom/client';
import { LocationPicker } from './components/LocationPicker';
import type { BaseLocation } from '../baseLocation';
import './index.css';

export function mountLocationPicker(onSelect: (location: BaseLocation) => void): ReturnType<typeof createRoot> {
  const rootElement = document.getElementById('react-root');
  if (!rootElement) {
    throw new Error('React root element not found');
  }

  const root = createRoot(rootElement);
  root.render(<LocationPicker onSelect={onSelect} />);

  return root;
}
