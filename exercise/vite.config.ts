import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

const envDir = path.resolve(__dirname);

/**
 * The browser calls /api/v1/exercise on its own origin; Vite forwards it to the exercise service, which supplies the map
 * token, the shared scenario library and the error log. The simulation itself runs in the browser, so the app works with
 * nothing behind this proxy at all.
 */
function proxy(mode: string) {
  const env = loadEnv(mode, envDir, '');
  const target = env.EXERCISE_PROXY_TARGET || 'http://127.0.0.1:8200';
  return { '/api': { target, changeOrigin: true } };
}

export default defineConfig(({ mode }) => ({
  base: './',
  envDir,
  plugins: [react()],
  build: { chunkSizeWarningLimit: 3000 },
  server: { port: 4100, proxy: proxy(mode) },
  preview: { host: '0.0.0.0', port: 8900, strictPort: true, allowedHosts: true, proxy: proxy(mode) },
}));
