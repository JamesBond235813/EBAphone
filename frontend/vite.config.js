import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 4173,
    strictPort: true,
    host: '0.0.0.0',
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
