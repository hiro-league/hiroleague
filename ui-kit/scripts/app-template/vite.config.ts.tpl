import { defineConfig } from 'vitest/config';
import { hiroVite } from './.kit/lib/vite-preset.js';

// The Vite settings every Hiro app shares (Tailwind, SvelteKit, the $kit and $hiro-app aliases, the dev proxy, the
// unit tests) are the kit's: .kit/lib/vite-preset.js, written by `npm run kit`, which every script that reads this
// file runs first. Only the app's own part is here: where its backend is.
// In dev, the UI runs on Vite and forwards API calls to __NAME__'s backend (:__PORT__).
// __API_ENV__ points a second UI at another backend (a session's own test servers).
export default defineConfig({ ...hiroVite({ apiEnv: '__API_ENV__', apiDefault: 'http://127.0.0.1:__PORT__' }) });
