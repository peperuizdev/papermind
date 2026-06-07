import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/webhook': {
        target: 'http://localhost:5678',
        changeOrigin: true,
      },
    },
  },
})
