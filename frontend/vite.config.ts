// vitest's defineConfig is vite's plus the `test` block — importing vite's
// would make the test config a type error.
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    // `@/…` beats `../../../` for imports that survive a file move.
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    // Proxy /api to the backend in dev so the browser sees one origin and
    // CORS never enters the picture locally. Production serves the built
    // assets from nginx with the same path prefix, so no code changes.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        // Monaco and the charting library are large and change rarely.
        // Splitting them keeps the app chunk small and cacheable.
        manualChunks: {
          monaco: ['@monaco-editor/react'],
          charts: ['recharts'],
          motion: ['framer-motion'],
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
