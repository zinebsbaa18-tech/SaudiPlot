import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Required for Replit's proxied iframe preview
    allowedHosts: true,
    host: '0.0.0.0',
    port: 5000,
    proxy: {
      // Forward /api calls to the FastAPI backend — avoids CORS on Replit.
      // We override the Origin header to match the backend's own host so the
      // backend's trusted-origin (CSRF) check passes. The Vite proxy acts as a
      // same-origin intermediary; the browser never talks to :8000 directly.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        headers: {
          Origin: 'http://localhost:8000',
        },
      },
    },
  },
})
