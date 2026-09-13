/// <reference types="vitest" />
import { defineConfig } from 'vite';

export default defineConfig({
  // Served from a project page (https://user.github.io/<repo>/) by default.
  // Override with BASE_PATH=/ for a custom domain or Cloudflare Pages.
  base: process.env.BASE_PATH ?? './',
  build: {
    target: 'es2020',
    sourcemap: false,
    reportCompressedSize: true,
    rollupOptions: {
      output: {
        // MapLibre is large and changes rarely: giving it its own chunk keeps
        // it in the browser cache across deploys of the app code.
        manualChunks: (id) => (id.includes('maplibre-gl') ? 'maplibre' : undefined),
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
