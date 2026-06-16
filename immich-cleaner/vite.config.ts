import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    host: '0.0.0.0',
    port: 2293,
    strictPort: true,
    watch: {
      usePolling: process.env.IMMICH_CLEANER_USE_POLLING === 'true'
    }
  },
  test: {
    include: ['src/**/*.test.ts']
  }
});
