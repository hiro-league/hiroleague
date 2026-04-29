import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const outDir = '../hiroserver/hirocli/src/hirocli/admin_svelte/static';

const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: outDir,
      assets: outDir,
      fallback: '200.html',
      precompress: false,
      strict: true
    }),
    paths: {
      base: process.env.HIRO_ADMIN_BASE ?? '/admin-next'
    }
  }
};

export default config;
