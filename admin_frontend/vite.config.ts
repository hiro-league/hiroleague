import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const hiroAdminOrigin = process.env.HIRO_ADMIN_ORIGIN ?? 'http://127.0.0.1:18083';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    proxy: {
      '/api': {
        target: hiroAdminOrigin,
        changeOrigin: true
      }
    }
  }
});
