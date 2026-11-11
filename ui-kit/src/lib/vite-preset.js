// The Vite settings every Hiro frontend shares, so an app's vite.config.ts keeps only what is its own (its backend's
// address). Plain JS: `npm run kit` copies it to .kit/lib/vite-preset.js, and an app imports it from there:
//
//   import { defineConfig } from 'vitest/config';
//   import { hiroVite } from './.kit/lib/vite-preset.js';
//   export default defineConfig({ ...hiroVite({ apiEnv: 'TRAINHIRO_API', apiDefault: 'http://127.0.0.1:8040' }) });
//
// It brings: Tailwind, SvelteKit (runes on, a static build with 200.html as the fallback, the `$kit` and `$hiro-app`
// aliases), the dev proxy for /api, a cache folder per dev server, and the unit tests' settings. An app that needs
// more merges its own keys after the spread (`server: { ...preset.server, port: 5190 }`).
//
// The file is bundled by Vite when it reads vite.config.ts, and its packages (tailwind, svelte-kit, the adapter) are
// found from where it sits: in an app, .kit/lib inside the app's own folder, so the app's node_modules. That is also
// why an app's scripts run `npm run kit` (which writes this file) before anything that reads vite.config.ts.
import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

// Node's process.env, without pulling in Node's type definitions for this one line.
const env = /** @type {{ process?: { env: Record<string, string | undefined> } }} */ (globalThis).process?.env ?? {};

/**
 * @param {object} [options]
 * @param {string} [options.apiEnv] The environment variable that points a second UI at another backend (e.g. 'TRAINHIRO_API').
 * @param {string} [options.apiDefault] Where the dev server forwards /api when the variable is not set (the app's backend).
 * @param {string} [options.kit] Where `$kit` points: the kit's copy in an app (default), `src/lib` in the kit itself.
 * @param {string} [options.app] Where `$hiro-app` points: the app's `src/lib/app` (default), `src/sample` in the kit.
 */
export function hiroVite({ apiEnv, apiDefault, kit = '.kit/lib', app = 'src/lib/app' } = {}) {
	return {
		// VITE_CACHE_DIR gives a second dev server (a session's own test UI) its own optimized-deps cache.
		// Sharing node_modules/.vite, the two servers rebuild it in turn and break each other's pages
		// ("504 Outdated Optimize Dep").
		cacheDir: env.VITE_CACHE_DIR,
		plugins: [
			tailwindcss(),
			sveltekit({
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
				},
				// Static build served by the app's backend. Pages are prerendered with relative asset paths (works
				// behind a proxy prefix); 200.html is the fallback for other routes.
				adapter: adapter({ fallback: '200.html' }),
				// The shared UI kit is read as source at $kit; it reads this app's own name, pages, menu and keys at $hiro-app.
				alias: { $kit: kit, '$hiro-app': app }
			})
		],
		// In dev, the UI runs on Vite and forwards API calls to the app's backend; the variable points a second UI at
		// another backend. changeOrigin off: the backend sees the page's own address (the sign-in sends the browser back to it).
		server: apiDefault ? { proxy: { '/api': { target: (apiEnv && env[apiEnv]) || apiDefault, changeOrigin: false } } } : {},
		// Unit tests (npm test): *.test.ts next to the code they test. A DOM environment makes Vitest treat the code as
		// browser code, as in the app: in Svelte's server build, effects never run.
		test: {
			include: ['src/**/*.test.ts'],
			environment: 'happy-dom',
			// the kit's Theme designer reads theme.css as text (?raw); Vitest would otherwise hand back an empty string
			css: { include: [/theme\.css/] }
		}
	};
}
