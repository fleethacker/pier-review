import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import { viteStaticCopy } from 'vite-plugin-static-copy';
import react from '@vitejs/plugin-react';

const cesiumSource = 'node_modules/cesium/Build/Cesium';
const cesiumBaseUrl = 'cesium';
const envDir = path.resolve(__dirname, '../..');

// The browser calls same-origin paths (api/modeling, api/agents); Vite forwards them to the services.
// That keeps CORS and hosting-prefix problems out of the app. REST lives under /api/v1, WebSockets under /ws.
function proxy(mode: string) {
  const env = loadEnv(mode, envDir, '');
  const modeling = env.MODELING_API_URL || 'http://localhost:8000';
  const agents = env.AGENTS_API_URL || 'http://localhost:8001';
  const rule = (target: string, prefix: string) => ({
    target,
    changeOrigin: true,
    ws: true,
    rewrite: (p: string) => p.replace(new RegExp(`^/${prefix}`), ''),
  });
  return {
    '/api/modeling': rule(modeling, 'api/modeling'),
    '/api/agents': rule(agents, 'api/agents'),
  };
}

export default defineConfig(({ mode }) => ({
  base: './',
  envDir,
  plugins: [
    react(),
    viteStaticCopy({
      targets: ['Workers', 'ThirdParty', 'Assets', 'Widgets'].map((dir) => ({
        src: `${cesiumSource}/${dir}`,
        dest: cesiumBaseUrl,
      })),
    }),
  ],
  define: { CESIUM_BASE_URL: JSON.stringify(cesiumBaseUrl) },
  server: { port: 4000, proxy: proxy(mode) },
  preview: { host: '0.0.0.0', port: 8888, strictPort: true, allowedHosts: true, proxy: proxy(mode) },
}));
