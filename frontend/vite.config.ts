import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Bind explicitly to 127.0.0.1: on Windows, Vite's default "localhost" can resolve to ::1 only,
// which makes the dev server unreachable over IPv4 (and to some tooling). Explicit is safer for
// a live demo.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
