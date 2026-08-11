import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {},
  preload: {},
  renderer: {
    root: resolve('src/renderer'),
    build: {
      rollupOptions: {
        input: {
          index: resolve('src/renderer/index.html'),
          overlay: resolve('src/renderer/overlay.html')
        }
      }
    },
    plugins: [react()],
    server: {
      fs: {
        allow: [resolve('src')]
      }
    },
    resolve: {
      alias: {
        '@': resolve('src/renderer')
      }
    }
  }
})
