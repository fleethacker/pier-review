import path from 'path'
import { defineConfig } from 'vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'
import react from '@vitejs/plugin-react'

const cesiumSource = 'node_modules/cesium/Build/Cesium'
const cesiumBaseUrl = 'cesium'

const apiProxy = {
    '/api/detect': { target: 'http://localhost:5050', changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api\/detect/, '/detect') },
    '/api/analyze': { target: 'http://localhost:5050', changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api\/analyze/, '/analyze') },
    '/api/wind-correct': { target: 'http://localhost:5051', changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api\/wind-correct/, '/wind-correct') },
    '/api/wind-tunnel': { target: 'http://localhost:5051', changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api\/wind-tunnel/, '/wind-tunnel') },
}

export default defineConfig({
    base: './',
    preview: { host: '0.0.0.0', port: 8888, strictPort: true, allowedHosts: true, proxy: apiProxy },
    plugins: [
        react(),
        viteStaticCopy({
            targets: [
                { src: `${cesiumSource}/Workers`, dest: cesiumBaseUrl },
                { src: `${cesiumSource}/ThirdParty`, dest: cesiumBaseUrl },
                { src: `${cesiumSource}/Assets`, dest: cesiumBaseUrl },
                { src: `${cesiumSource}/Widgets`, dest: cesiumBaseUrl },
            ],
        }),
    ],
    define: {
        CESIUM_BASE_URL: JSON.stringify(cesiumBaseUrl),
    },
    envDir: path.resolve(__dirname, '../..'),
    server: {
        port: 4000,
        proxy: {
            '/api/detect': {
                target: 'http://localhost:5050',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api\/detect/, '/detect'),
            },
            '/api/analyze': {
                target: 'http://localhost:5050',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api\/analyze/, '/analyze'),
            },
            '/api/wind-correct': {
                target: 'http://localhost:5051',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api\/wind-correct/, '/wind-correct'),
            },
            '/api/wind-tunnel': {
                target: 'http://localhost:5051',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api\/wind-tunnel/, '/wind-tunnel'),
            },
        },
    },
})