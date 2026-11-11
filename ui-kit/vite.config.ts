import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// Node's process.env, without pulling in Node's type definitions for this one line.
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};

// The kit's own project: its gallery (src/routes) and its checks and tests. The apps do not build this; they read
// src/lib as source (README.md).
export default defineConfig({
	cacheDir: env.VITE_CACHE_DIR,
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
			},
			adapter: adapter({ fallback: '200.html' }),
			// As in an app: the kit's files import each other at $kit, and read the app at $hiro-app. Here the app is
			// the sample one (src/sample), which the gallery and the tests run against.
			alias: {
				$kit: 'src/lib',
				'$hiro-app': 'src/sample'
			}
		})
	],
	// Unit tests: *.test.ts next to the code they test. A DOM environment makes Vitest treat the code as browser
	// code, as in the apps: in Svelte's server build, effects never run.
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'happy-dom',
		// the kit's Theme designer reads theme.css as text (?raw); Vitest would otherwise hand back an empty string
		css: { include: [/theme\.css/] }
	}
});
