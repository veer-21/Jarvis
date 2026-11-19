import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Relative asset paths: the same build is loaded by Electron (file://) and served by the backend at /
  base: './',
  server: {
    host: '127.0.0.1',
    port: 3000
  }
})
