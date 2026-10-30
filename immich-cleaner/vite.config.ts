import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [
    sveltekit({
      preprocess: vitePreprocess(),
      adapter: adapter({
        out: 'build'
      })
    })
  ],
  server: {
    allowedHosts: ['sawas-mac-studio.tailb3cfd6.ts.net'],
    host: '0.0.0.0',
    port: 2222,
    strictPort: true,
    watch: {
      usePolling: process.env.IMMICH_CLEANER_USE_POLLING === 'true'
    }
  },
  test: {
    include: ['src/**/*.test.ts']
  }
});
