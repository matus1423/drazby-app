import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre 6 si načítava worker relatívne k sebe (new URL(..., import.meta.url)) –
  // predbalenie cez optimizeDeps by tú cestu rozbilo.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  worker: { format: 'es' },
  build: { chunkSizeWarningLimit: 1500 },
})
