import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Chrome } from './Chrome';
import { exerciseApp } from './index';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Chrome def={exerciseApp} />
  </StrictMode>,
);
