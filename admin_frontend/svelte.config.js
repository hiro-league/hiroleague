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
      base: ''
    },
    // The shared UI kit (@hiroleague/ui, ../ui-kit) is read as source at $kit; it reads this app's own name, pages,
    // menu and keys at $hiro-app (src/lib/app). UI kit step 2b.
    alias: {
      $kit: 'node_modules/@hiroleague/ui/src/lib',
      '$hiro-app': 'src/lib/app'
    }
  }
};

export default config;
