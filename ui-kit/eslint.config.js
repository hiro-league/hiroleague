// Lint (npm run lint, also part of npm run check). Type-aware, so it can see promises nobody waits
// for or catches: a rejected one fails silently in the browser.
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';

export default defineConfig(
	{ ignores: ['build/', '.svelte-kit/', 'node_modules/', 'src/lib/components/ui/'] }, // shadcn's components: added with its CLI, kept as it writes them
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
			// Off: the links it flags are API files (apiUrl already adds the base path) and HA pages.
			// Links to the app's own pages use resolve().
			'svelte/no-navigation-without-resolve': 'off',
			// `_name` marks a value left out on purpose (e.g. `const { version: _v, ...rest } = plan`).
			'@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', destructuredArrayIgnorePattern: '^_' }]
		}
	},
	// House rules that can be checked by pattern (docs/frontend-best-practices.md, section 11), so
	// they don't depend on remembering them. Each message says what to use instead.
	{
		files: ['src/**/*.ts', 'src/**/*.svelte'],
		ignores: ['src/lib/components/ui/**'],
		rules: {
			'no-restricted-globals': [
				'error',
				...['confirm', 'alert', 'prompt'].map((name) => ({ name, message: "Use ask() from $lib/ui/confirm.svelte: the app's own dialog." })),
				...['localStorage', 'sessionStorage'].map((name) => ({
					name,
					message: 'Use persisted() or load/save from $lib/state/persist, with the key listed in state/prefs.ts.'
				}))
			],
			'no-restricted-syntax': [
				'error',
				...['CallExpression[callee.name="setInterval"]', 'CallExpression[callee.property.name="setInterval"]'].map((selector) => ({
					selector,
					message: 'Use poll() or repeat() from $lib/state/poll.svelte: they never overlap and rest while the tab is hidden.'
				})),
				// Status colours are theme tokens (layout.css). Green text means "fine": text-success. Red
				// text at these shades means "wrong": text-destructive. Colours that carry data (chart bars,
				// dots, a lamp's glow) stay literal and are not matched.
				...['Literal[value=/text-(green|emerald)-[0-9]|text-red-[5-7]00/]', 'TemplateElement[value.raw=/text-(green|emerald)-[0-9]|text-red-[5-7]00/]', 'SvelteLiteral[value=/text-(green|emerald)-[0-9]|text-red-[5-7]00/]'].map(
					(selector) => ({ selector, message: 'Status colours are tokens: text-success for fine, text-destructive for wrong.' })
				),
				// Dates and times go through $lib/format/time: 12-hour with AM/PM, always with the day (CLAUDE.md).
				// The browser's locale can be 24-hour. A number's own toLocaleString() (no arguments) is fine.
				...[
					'CallExpression[callee.property.name=/^toLocale(Date|Time)String$/]',
					'CallExpression[callee.property.name="toLocaleString"][callee.object.type="NewExpression"]',
					'CallExpression[callee.property.name="toLocaleString"][arguments.length>0]',
					'NewExpression[callee.object.name="Intl"][callee.property.name="DateTimeFormat"]'
				].map((selector) => ({ selector, message: 'Dates and times: use $lib/format/time (dateTime, clock, day, shortDate…): 12-hour with AM/PM, always with the day.' }))
			]
		}
	},
	{
		// The one place that writes dates and times.
		files: ['src/lib/format/time.ts'],
		rules: { 'no-restricted-syntax': 'off' }
	},
	{
		// The one place allowed to touch the browser's storage, and the one timer everything else uses.
		files: ['src/lib/state/persist.ts', 'src/lib/state/poll.svelte.ts'],
		rules: { 'no-restricted-globals': 'off', 'no-restricted-syntax': 'off' }
	},
	{
		// Shared layers never depend on a feature (a feature may use them all). Types are allowed: the
		// API layer names the shapes the floor plan model defines.
		files: ['src/lib/api/**', 'src/lib/state/**', 'src/lib/ui/**', 'src/lib/format/**', 'src/lib/components/**'],
		rules: {
			'@typescript-eslint/no-restricted-imports': [
				'error',
				{ patterns: [{ group: ['$lib/features/*', '$lib/features/**'], allowTypeImports: true, message: 'Shared code must not import a feature; move what both need into lib/.' }] }
			]
		}
	},
	{
		// Config files run in Node, outside the app's TypeScript project.
		files: ['*.js', '*.ts'],
		extends: [ts.configs.disableTypeChecked],
		languageOptions: { globals: { ...globals.node } }
	}
);
