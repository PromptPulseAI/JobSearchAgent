import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // Proxy API calls to the Python backend (when running locally)
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
