// The ESLint setup every Hiro frontend shares, so an app's eslint.config.js keeps only what is its own (shared-code
// plan, step 2; each app had the same 40 lines). Plain JS: `npm run kit` copies it to .kit/lib/eslint-preset.js, and an
// app imports it from there, as it does vite-preset.js:
//
//   import { defineConfig } from 'eslint/config';
//   import { hiroEslint } from './.kit/lib/eslint-preset.js';
//   export default defineConfig(...hiroEslint({ dirname: import.meta.dirname }), { ...the app's own rules });
//
// It brings: the recommended JS, TypeScript and Svelte rules, type-aware (so it can see promises nobody waits for or
// catches: a rejected one fails silently in the browser), the house settings below, the kit's house rules
// (eslint-rules.js), and config files linted as Node. The app's own rules go after it, and win where they name the same
// rule for the same files. Its packages are found from where it sits: in an app, .kit/lib inside the app's own folder,
// so the app's node_modules.
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';
import { hiroRules } from './eslint-rules.js';

/**
 * @param {object} options
 * @param {string} options.dirname The app's folder (`import.meta.dirname`): where its TypeScript project is.
 * @param {string[]} [options.ignores] More folders ESLint skips, beside the build output, node_modules, scripts/ (plain
 *   Node, outside the app's TypeScript project) and .kit/ (the kit's copy, checked in the kit).
 */
export function hiroEslint({ dirname, ignores = [] }) {
	return [
		{ ignores: ['build/', '.svelte-kit/', 'node_modules/', 'scripts/', '.kit/', ...ignores] },
		js.configs.recommended,
		...ts.configs.recommended,
		...svelte.configs.recommended,
		{
			languageOptions: {
				globals: { ...globals.browser },
				parserOptions: { projectService: true, tsconfigRootDir: dirname, extraFileExtensions: ['.svelte'] }
			}
		},
		{
			files: ['**/*.svelte', '**/*.svelte.ts'],
			languageOptions: { parserOptions: { parser: ts.parser } }
		},
		{
			rules: {
				'@typescript-eslint/no-floating-promises': 'error',
				// Off: it flags every local Map, Set or Date, also the plain ones used inside a function.
				// Reactive collections here are $state arrays and records.
				'svelte/prefer-svelte-reactivity': 'off',
				// Off: the links it flags are API files (apiUrl already adds the base path) and pages outside the app
				// (Home Assistant's). Links to the app's own pages use resolve().
				'svelte/no-navigation-without-resolve': 'off',
				// `_name` marks a value left out on purpose (e.g. `const { version: _v, ...rest } = plan`).
				'@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', destructuredArrayIgnorePattern: '^_' }]
			}
		},
		// House rules checked by pattern (storage, dialogs, timers, status colours, dates), shared by every Hiro frontend
		...hiroRules,
		{
			// Config files run in Node, outside the app's TypeScript project.
			files: ['*.js', '*.ts'],
			extends: [ts.configs.disableTypeChecked],
			languageOptions: { globals: { ...globals.node } }
		}
	];
}
