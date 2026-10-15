import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      '/plugins': 'http://localhost:8000',
      '/analyze': 'http://localhost:8000',
      '/transcribe': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/visualize': 'http://localhost:8000',
      '/process': 'http://localhost:8000',
      '/pipeline': 'http://localhost:8000',
      '/config': 'http://localhost:8000',
      '/monitor': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/webhook': 'http://localhost:8000',
    }
  },
  build: {
    outDir: 'dist',
  }
});
