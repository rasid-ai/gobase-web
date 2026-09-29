import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  // MapLibre loads its GeoJSON parser as a web worker, and finds it with
  // `new URL('./maplibre-gl-worker.mjs', import.meta.url)` — relative to
  // wherever its own module was served from. Pre-bundling moves the module to
  // .vite/deps but leaves the worker behind, so that URL 404s, the worker
  // never starts, and every GeoJSON source stays unloaded: no footprints, no
  // drawn layers, and no error, because the request is made by the worker
  // loader rather than the map. Raster tiles are unaffected — they never reach
  // the worker — which is why the basemap looks fine.
  //
  // Excluding it keeps the module beside its worker. Development only; the
  // production build resolves the worker through Rollup and is not affected.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  server: {
    port: 5173,
    // Proxy /api to Django so development is same-origin, exactly like
    // production behind nginx (context/architecture.md). The refresh cookie
    // then behaves identically in both, and CORS is never needed at all.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
