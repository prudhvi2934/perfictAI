import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Forward /api/* requests to the FastAPI backend running on port 8000.
    // This way the frontend can call fetch('/api/...') without CORS issues.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // Strip the /api prefix before forwarding to FastAPI.
        // e.g. /api/transactions/pending → /transactions/pending
        rewrite: path => path.replace(/^\/api/, ''),
      },
    },
  },
})
