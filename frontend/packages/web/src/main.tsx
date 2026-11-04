import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { demoApp } from './apps/demo';
import { exerciseApp } from './apps/exercise';
import { mooringApp } from './apps/mooring';
import { registerApp } from './scene/app';
import { SceneStore } from './scene/store';
import { Shell } from './shell/Shell';
import './styles/index.css';

registerApp(mooringApp);
registerApp(exerciseApp);
if (import.meta.env.DEV) registerApp(demoApp);

const store = new SceneStore();
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Shell store={store} />
  </StrictMode>,
);
