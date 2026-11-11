// The house lint rules of the Hiro frontends, as an ESLint flat-config fragment: rules that can be checked by
// pattern, so they don't depend on remembering them. Each message says which kit piece to use instead.
// The rules and their reasons: mintdocs/build/ui-kit/ui-guidelines.mdx.
//
// Plain JS (no imports), so the kit and every app load it the same way. The kit's own eslint.config.js uses it
// from here; an app uses its copy, which `npm run kit` writes to .kit/lib/eslint-rules.js:
//   import { hiroRules } from './.kit/lib/eslint-rules.js';
//   export default defineConfig(..., ...hiroRules, ...);
// A rule that is one app's own (e.g. "shared layers never import a feature") stays in that app's config.

const STATUS_COLOURS = '/text-(green|emerald)-[0-9]|text-red-[5-7]00/';

export const hiroRules = [
	{
		files: ['src/**/*.ts', 'src/**/*.svelte'],
		ignores: ['src/lib/components/ui/**'],
		rules: {
			'no-restricted-globals': [
				'error',
				...['confirm', 'alert', 'prompt'].map((name) => ({
					name,
					message: "Use ask() from $kit/ui/confirm.svelte (ConfirmDelete for a delete button): the app's own dialog."
				})),
				...['localStorage', 'sessionStorage'].map((name) => ({
					name,
					message: 'Use persisted() or load/save from $kit/state/persist, with the key listed in the app\'s prefs.ts.'
				}))
			],
			'no-restricted-syntax': [
				'error',
				...['CallExpression[callee.name="setInterval"]', 'CallExpression[callee.property.name="setInterval"]'].map((selector) => ({
					selector,
					message: 'Use poll() or repeat() from $kit/state/poll.svelte: they never overlap and rest while the tab is hidden.'
				})),
				// Status colours are theme tokens (theme.css). Green text means "fine": text-success. Red text at
				// these shades means "wrong": text-destructive. Things sorted into kinds use the category colours
				// (CAT, categoryOf from $kit/ui/category); a status lamp is StatusDot. Colours that carry data
				// (chart bars, a lamp's own glow) stay literal and are not matched.
				...[`Literal[value=${STATUS_COLOURS}]`, `TemplateElement[value.raw=${STATUS_COLOURS}]`, `SvelteLiteral[value=${STATUS_COLOURS}]`].map(
					(selector) => ({
						selector,
						message:
							'Status colours are tokens: text-success for fine, text-destructive for wrong (StatusDot for a lamp). Kinds use the category colours from $kit/ui/category.'
					})
				),
				// Dates and times go through $kit/format/time: 12-hour with AM/PM, always with the day. The browser's
				// locale can be 24-hour. A number's own toLocaleString() (no arguments) is fine, but $kit/format/number
				// (count, decimal, percent, bytes) is preferred.
				...[
					'CallExpression[callee.property.name=/^toLocale(Date|Time)String$/]',
					'CallExpression[callee.property.name="toLocaleString"][callee.object.type="NewExpression"]',
					'CallExpression[callee.property.name="toLocaleString"][arguments.length>0]',
					'NewExpression[callee.object.name="Intl"][callee.property.name="DateTimeFormat"]'
				].map((selector) => ({
					selector,
					message:
						'Dates and times: use $kit/format/time (dateTime, clock, day, shortDate...): 12-hour with AM/PM, always with the day. Numbers: $kit/format/number.'
				}))
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
	}
];
