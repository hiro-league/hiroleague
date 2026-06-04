import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const hiroAdminOrigin = process.env.HIRO_ADMIN_ORIGIN ?? 'http://127.0.0.1:18083';

// HIRO_FAST_BUILD=1 (set by dev-sync-fast.sh) skips production-only polish that is
// useless for locally-served dev assets: JS/CSS minification and the per-chunk gzip
// size report. Release builds (dev-sync.sh / CI) leave it unset for full optimization.
const fastBuild = process.env.HIRO_FAST_BUILD === '1';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  build: {
    minify: fastBuild ? false : 'esbuild',
    cssMinify: !fastBuild,
    reportCompressedSize: !fastBuild,
    sourcemap: false
  },
  server: {
    proxy: {
      '/api': {
        target: hiroAdminOrigin,
        changeOrigin: true
      }
    }
  }
});
