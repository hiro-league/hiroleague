// Creates a Hiro app's frontend from nothing: the SvelteKit project, wired to the shared UI kit, with sign-in, the menu,
// the Logs page and Settings (HiroLeague, Users & Roles, and AI if asked) already in place.
//
//   node scripts/new-app.mjs <folder> <Name> [--port 8050] [--ai] [--icon Shapes]
//
//   <folder>  where the frontend goes (usually <app repo>/frontend); it must be empty or not exist yet
//   <Name>    the app's name, as people read it ("TrainHiro"); its short form (lower case) names the storage prefix,
//             the loggers and the dev proxy variable (TRAINHIRO_API)
//   --port    where its backend listens in dev (default 8050)
//   --ai      adds Settings -> "AI from HiroLeague" (the app asks the core's AI for something)
//   --icon    a Lucide icon for the menu and the sign-in page (default Shapes)
//
// What it writes: the files in scripts/app-template/ (the project's own files, with the name filled in), the app's facts
// (src/lib/app/*) from this kit's src/sample/ with the name filled in, and the files that depend on the flags (package.json,
// the menu, the pages, the prefs, the Settings route). Then, in the new folder: `npm install` and `npm run check`
// (HIRO_KIT_DIR names this kit's folder when the app does not sit beside the HiroLeague checkout; README.md).
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const kitDir = resolve(here, '..');
const templateDir = join(here, 'app-template');
const sampleDir = join(kitDir, 'src/sample');

const fail = (message) => {
	console.error(`new-app: ${message}`);
	process.exit(1);
};

// --- The command line
const args = process.argv.slice(2);
const flags = { ai: false, port: '8050', icon: 'Shapes' };
const positional = [];
for (let i = 0; i < args.length; i++) {
	const a = args[i];
	if (a === '--ai') flags.ai = true;
	else if (a === '--port' || a === '--icon') {
		const value = args[++i];
		if (!value) fail(`${a} needs a value`);
		flags[a.slice(2)] = value;
	} else if (a.startsWith('--')) fail(`unknown option ${a}`);
	else positional.push(a);
}
const [folderArg, name] = positional;
if (!folderArg || !name || positional.length > 2) fail('usage: node scripts/new-app.mjs <folder> <Name> [--port 8050] [--ai] [--icon Shapes]');
if (!/^[A-Za-z][A-Za-z0-9]*$/.test(name)) fail(`the name "${name}" must be letters and digits, starting with a letter (e.g. TrainHiro)`);
if (!/^\d+$/.test(flags.port)) fail(`--port must be a number, not "${flags.port}"`);
if (!/^[A-Z][A-Za-z0-9]*$/.test(flags.icon)) fail(`--icon must be a Lucide icon's name (e.g. Shapes), not "${flags.icon}"`);

const folder = resolve(folderArg);
if (existsSync(folder) && (!statSync(folder).isDirectory() || readdirSync(folder).length > 0)) fail(`${folder} is not empty; this script only writes into an empty folder`);

const slug = name.toLowerCase();
const values = { __NAME__: name, __SLUG__: slug, __API_ENV__: `${name.toUpperCase()}_API`, __PORT__: flags.port };
const fill = (text) => Object.entries(values).reduce((out, [key, value]) => out.replaceAll(key, value), text);

const write = (rel, text) => {
	const to = join(folder, rel);
	mkdirSync(dirname(to), { recursive: true });
	writeFileSync(to, text.endsWith('\n') ? text : `${text}\n`);
};
const readSample = (file) => readFileSync(join(sampleDir, file), 'utf8');

/** Replaces `from` with `to` in `text`, and fails when `from` is not there (the sample changed under this script). */
const swap = (text, from, to, where) => {
	if (!text.includes(from)) fail(`src/sample/${where} no longer has "${from}"; update scripts/new-app.mjs`);
	return text.replaceAll(from, to);
};

// --- 1) The template's files, as they are (names filled in); a few are stored under another name
const renamed = { gitignore: '.gitignore', npmrc: '.npmrc', vscode: '.vscode' };
const walk = (dir) => readdirSync(dir).flatMap((entry) => (statSync(join(dir, entry)).isDirectory() ? walk(join(dir, entry)) : [join(dir, entry)]));
for (const file of walk(templateDir)) {
	const rel = relative(templateDir, file)
		.split(/[\\/]/)
		.map((part) => renamed[part] ?? part)
		.join('/')
		.replace(/\.tpl$/, ''); // *.tpl: configs that tools would otherwise pick up from this folder
	const to = join(folder, rel);
	mkdirSync(dirname(to), { recursive: true });
	if (/\.(svg|json|mjs)$/.test(file) && !/(components|extensions|settings)\.json$/.test(file)) copyFileSync(file, to);
	else writeFileSync(to, fill(readFileSync(file, 'utf8')));
}

// --- 2) package.json: the kit's own packages (its devDependencies are what an app lists), the app's scripts
const kitPackage = JSON.parse(readFileSync(join(kitDir, 'package.json'), 'utf8'));
write(
	'package.json',
	JSON.stringify(
		{
			name: `${slug}-frontend`,
			private: true,
			version: '0.0.1',
			type: 'module',
			scripts: {
				kit: 'node scripts/kit-sync.mjs',
				// Every script that reads vite.config.ts starts with `kit`: the config imports the kit's copy (.kit/lib/vite-preset.js),
				// which a fresh clone only has after `npm run kit` (`prepare` runs it on npm install).
				dev: 'npm run kit && vite dev',
				build: 'npm run kit && vite build',
				preview: 'vite preview',
				prepare: "node scripts/kit-sync.mjs && svelte-kit sync || echo ''",
				check: 'npm run kit && svelte-kit sync && svelte-check --tsconfig ./tsconfig.json && eslint . && vitest run',
				'check:watch': 'svelte-kit sync && svelte-check --tsconfig ./tsconfig.json --watch',
				lint: 'eslint .',
				test: 'npm run kit && vitest run',
				'test:watch': 'vitest'
			},
			devDependencies: kitPackage.devDependencies,
			dependencies: {}
		},
		null,
		'\t'
	)
);

// --- 3) The app's facts (src/lib/app): the sample's, with the name filled in
const copyFacts = (file, swaps, header) => {
	let text = readSample(file);
	if (header) text = text.replace(/^(\/\/.*\n)+/, header + '\n'); // the sample's own header talks about the gallery
	for (const [from, to] of swaps) text = swap(text, from, to, file);
	write(`src/lib/app/${file}`, text);
};
copyFacts('app.ts', [
	["name: 'Hiro kit'", `name: '${name}'`],
	["homeTitle: 'Gallery'", "homeTitle: 'Home'"],
	["storagePrefix: 'hirokit.'", `storagePrefix: '${slug}.'`],
	['Shapes', flags.icon]
], `// What makes this app ${name}, for the code every Hiro app shares: the kit reads it at $hiro-app (this folder, src/lib/app).
//   app.ts - this file: the name, the icon, the words
//   api.ts, prefs.ts, pages.ts, menu.ts, notices.ts - what the kit needs of the app's API, keys, pages, menu and live notices
//   hiroleague.ts, users.ts, logs.ts${flags.ai ? ', ai.ts' : ''} - the app's words on the standard pages`);
copyFacts('hiroleague.ts', [
	["siteLabel: 'kit'", `siteLabel: '${slug}'`],
	["edits: 'its AI profiles and roles'", "edits: 'the roles'"],
	['The sample app', `${name}`]
].filter(([from]) => readSample('hiroleague.ts').includes(from)));
copyFacts('users.ts', [
	['Hiro kit keeps', `${name} keeps`],
	['The sample app', `${name}`]
].filter(([from]) => readSample('users.ts').includes(from)));
copyFacts('notices.ts', [], `// The notices ${name}'s backend sends its open pages ($kit/live listens). 'hello' is every Hiro app's; add the app's own.`);
if (flags.ai) copyFacts('ai.ts', [['The sample app', name], ['the sample app', name]].filter(([from]) => readSample('ai.ts').includes(from)), `// What ${name} says on its AI pages ($hiro-app/ai): see pages/ai/types.ts. Replace the words with what the app asks an AI for.`);
copyFile(join(sampleDir, 'theme.css'), join(folder, 'src/lib/app/theme.css'));

function copyFile(from, to) {
	mkdirSync(dirname(to), { recursive: true });
	copyFileSync(from, to);
}

// api.ts: the sample's types, the real calls (who is asking, the sign-in through the backend's auth routes)
{
	const sample = readSample('api.ts');
	const cut = sample.indexOf('export const getMe');
	if (cut < 0) fail('src/sample/api.ts no longer has getMe; update scripts/new-app.mjs');
	const types = sample.slice(0, cut).replace(/^\/\/.*\n\/\/.*\n\n?/, '');
	write(
		'src/lib/app/api.ts',
		`// What the shared code (@hiroleague/ui) reads of this app's API: who is asking, and the sign-in.
// The kit imports them from here ($hiro-app/api), so it never names an app's own API files.
import { api, apiUrl } from '$kit/api/client';

${types.trimEnd()}

/** Who is asking (the backend's /api/me). */
export const getMe = () => api<Me>('me');

/** Start a sign-in and come back to \`next\`: off to HiroLeague's sign-in page, through the backend, which knows
 * its address (the backend's /api/auth/start). */
export const startSignIn = (next: string) => {
	location.href = apiUrl(\`auth/start?next=\${encodeURIComponent(next)}\`);
};

/** End this app's session; \`then\` is HiroLeague's sign-out to go to next (it ends that session too), or null
 * when the backend doesn't know HiroLeague's address. */
export const signOut = () => api<{ then: string | null }>('auth/logout', { method: 'POST' });
`
	);
}

// logs.ts: the app's log sources and the areas of its loggers (to be extended with the backend's loggers)
write(
	'src/lib/app/logs.ts',
	`// What this app gives the kit's Logs page: its log sources, its loggers' areas${flags.ai ? '' : ' (no LLM requests tab: it asks no AI)'}.
import type { LogsApp } from '$kit/pages/logs/types';

export const LOGS: LogsApp = {
	name: '${name}',
	sources: [
		{ value: '${slug}', label: '${name}' },
		{ value: 'crash', label: 'Crashes' }
	],
	// Logger name (or its start) -> the area, in words. Add the backend's own loggers (\`${slug}.*\`) here.
	areas: [
		['${slug}.app', 'Web server'],
		['${slug}.auth', 'Users and roles'],
		['${slug}.hiroleague', 'HiroLeague'],
		['uvicorn', 'Web server'],
		['crash', 'Crashes'],
		['py.warnings', 'Python warnings']
	],
	llm: null
};
`
);

// --- 4) The pages, the menu and the browser keys (what each page needs and what is in the menu)
const aiTab = flags.ai ? "\n\t\t\t{ value: 'fromhiro', title: 'AI from HiroLeague', icon: Sparkles, shown: settings }," : '';
write(
	'src/lib/app/menu.ts',
	`// ${name}'s side menu: its groups, their pages, and each page's tabs. How a menu works (two levels, tabs as
// icons on a page's row, sub-tabs) and who gets what of it: $kit/components/menu, the same in every Hiro app.
import type { Me } from '$hiro-app/api';
import type { MenuPage } from '$kit/components/menu';
import { can } from '$kit/state/pages';
import { House, Puzzle, ScrollText, Settings, ShieldCheck, ${flags.ai ? 'Sparkles, ' : ''}UserCog, Users } from '@lucide/svelte';

// Settings' tabs (the Settings route draws them from here too): the HiroLeague connection${flags.ai ? ' and AI' : ''} for those who may change
// settings, Users and Roles for owners.
const settings = (me: Me | null) => can(me, 'settings', 'use');
const owner = (me: Me | null) => !!me?.owner;

export const MENU_PAGES = {
	home: { route: '/', title: 'Home', icon: House },
	logs: { route: '/logs', title: 'Logs', icon: ScrollText },
	settings: {
		route: '/settings',
		title: 'Settings',
		icon: Settings,
		pref: 'settings.tab',
		tabs: [
			{ value: 'hiroleague', title: 'HiroLeague', icon: Puzzle, shown: settings }, // ${name} as the HiroLeague core's extension${aiTab}
			{
				value: 'access',
				title: 'Users & Roles',
				icon: UserCog,
				subs: [
					{ value: 'users', title: 'Users', icon: Users, shown: owner },
					{ value: 'roles', title: 'Roles', icon: ShieldCheck, shown: owner }
				]
			}
		]
	}
} satisfies Record<string, MenuPage>;

type PageKey = keyof typeof MENU_PAGES;

// The groups, in menu order.
export const MENU_GROUPS: { id: string; title: string; pages: PageKey[] }[] = [
	{ id: 'app', title: '${name}', pages: ['home', 'logs', 'settings'] }
];
`
);
write(
	'src/lib/app/pages.ts',
	`// ${name}'s pages and which feature opens each (the backend's access rules must name the same features). The rules that
// read this list (who may open a page, what is in their menu, where they start): $kit/state/pages.
import type { Page } from '$kit/state/pages';

// Route ids (as SvelteKit names them, whatever the base path). A page opens with any of its features, at
// \`need\` (look, unless it says use).
export const PAGES: Page[] = [
	{ route: '/', any: ['home'] },
	{ route: '/logs', any: ['logs'] },
	{ route: '/settings', any: ['settings'], need: 'use' } // its tabs change things; Users and Roles: owners
];
`
);
write(
	'src/lib/app/prefs.ts',
	`// Every key this app keeps in the browser (localStorage, each prefixed with app.ts's \`storagePrefix\`), in one place,
// so two features never share a key by accident. Add a key here before using it; \`load\`, \`save\`, \`persisted\` and
// \`UrlTab\` only take these.

export const PREF_KEYS = [
	// The app
	'sidebar.open',
	'sidebar.closedGroups', // menu groups folded away
	'sidebar.width', // the menu's width in pixels, dragged by its edge
	'settings.tab',
	'logs.tab', // the Logs page's tabs (the kit page names the key)
	'gallery.theme' // the Theme designer's draft, if the app has one (the kit's pages read the key)
] as const;

export type PrefKey = (typeof PREF_KEYS)[number];
`
);

// --- 5) The Settings route: the map of its tabs (the shell is the kit's: pages/settings/settings-page.svelte)
const aiImport = flags.ai ? "\n\timport AiFromHiroLeague from '$kit/pages/ai/ai-tab.svelte';" : '';
const aiContent = flags.ai ? ' fromhiro,' : '';
const aiSnippet = flags.ai ? '\n{#snippet fromhiro()}<AiFromHiroLeague />{/snippet}' : '';
write(
	'src/routes/settings/+page.svelte',
	`<script lang="ts">
	// Settings: the tabs and who gets them come from the menu (menu.ts); the shell (the tab handling, the address ?tab=users,
	// the remembered inner tab) is the kit's. This file says what is in each tab: add the app's own tabs to the menu, then here.
	import SettingsPage from '$kit/pages/settings/settings-page.svelte';
	import HiroLeagueSettings from '$kit/pages/hiroleague/hiroleague-settings.svelte';${aiImport}
	import UsersTab from '$kit/pages/users/users-tab.svelte';
	import RolesTab from '$kit/pages/users/roles-tab.svelte';
</script>

<SettingsPage content={{ hiroleague,${aiContent} users, roles }} />

{#snippet hiroleague()}<HiroLeagueSettings />{/snippet}${aiSnippet}
{#snippet users()}<UsersTab />{/snippet}
{#snippet roles()}<RolesTab />{/snippet}
`
);

console.log(`new-app: wrote ${name} to ${folder}
Next, in that folder:
  npm install       (the kit is read from ../../../hiroleague/ui-kit; set HIRO_KIT_DIR to ${kitDir} if it is elsewhere)
  npm run check
  npm run dev
Then: add the app's pages under src/routes (and to src/lib/app/menu.ts and pages.ts), and its backend's /api/me, /api/auth/*
and the standard pages' endpoints (mintdocs/build/ui-kit/standard-pages-api.mdx).`);
