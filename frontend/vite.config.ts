/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // ws: true wajib — tanpa ini browser tidak bisa handshake WebSocket
      // (dev server 5173), sehingga overlay deteksi Live View tak pernah terisi.
      // Target proxy dari API_URL; server memakai API_URL=http://localhost:7701
      '/api': { target: process.env.API_URL || 'http://localhost:8000', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
  },
})
