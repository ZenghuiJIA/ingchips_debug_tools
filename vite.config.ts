import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from 'tailwindcss'
import autoprefixer from 'autoprefixer'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
  },
  css: {
    postcss: {
      plugins: [
        tailwindcss({
          content: [
            './index.html',
            './src/**/*.{vue,js,ts,jsx,tsx}',
          ],
          darkMode: 'class',
          theme: {
            extend: {
              colors: {
                border: 'hsl(var(--border))',
                background: 'hsl(var(--background))',
                foreground: 'hsl(var(--foreground))',
              },
              fontFamily: {
                mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'Courier New', 'monospace'],
              },
            },
          },
          plugins: [],
        }),
        autoprefixer(),
      ],
    },
  },
})
