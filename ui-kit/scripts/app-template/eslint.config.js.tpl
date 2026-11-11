// Lint (npm run lint, also part of npm run check). Type-aware, so it can see promises nobody waits
// for or catches: a rejected one fails silently in the browser.
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';
import { hiroRules } from './.kit/lib/eslint-rules.js';

export default defineConfig(
	{ ignores: ['build/', '.svelte-kit/', 'node_modules/', 'scripts/', '.kit/'] }, // .kit/: the shared UI kit's copy, checked in the kit; scripts/: plain Node, outside the app's TypeScript project
	js.configs.recommended,
	ts.configs.recommended,
	svelte.configs.recommended,
	{
		languageOptions: {
			globals: { ...globals.browser },
			parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname, extraFileExtensions: ['.svelte'] }
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
			// Off: the links it flags are API files (apiUrl already adds the base path).
			// Links to the app's own pages use resolve().
			'svelte/no-navigation-without-resolve': 'off',
			// `_name` marks a value left out on purpose (e.g. `const { version: _v, ...rest } = plan`).
			'@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', destructuredArrayIgnorePattern: '^_' }]
		}
	},
	// House rules checked by pattern (storage, dialogs, timers, status colours, dates): the kit's, shared by every Hiro frontend.
	// Rules that are this app's own go below.
	...hiroRules,
	{
		// Config files run in Node, outside the app's TypeScript project.
		files: ['*.js', '*.ts'],
		extends: [ts.configs.disableTypeChecked],
		languageOptions: { globals: { ...globals.node } }
	}
);
