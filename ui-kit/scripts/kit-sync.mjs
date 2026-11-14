// Brings an app's copy of the shared UI kit (@hiroleague/ui) up to date: this kit's src/lib, copied to the app's
// .kit/lib (not committed; $kit points there: SvelteKit takes an alias ending in ".kit" for a file, hence the lib
// folder). One copy, here in the kit, that every app runs from its frontend folder (shared-code plan, step 2; each app
// had its own copy of this file):
//
//   "kit": "node ../../hiroleague/ui-kit/scripts/kit-sync.mjs"      (package.json; dev, build, check and test start with it)
//
// The path is where the HiroLeague checkout sits beside the app's repo, on the PC and in the image (/ui and
// /hiroleague/ui-kit). The app is the folder npm runs it in.
// A copy, not a link, so the kit's files use the app's own svelte and bits-ui (one of each), and a folder of the app's
// own, not node_modules: the dev server watches it and reloads on a change (under node_modules the browser kept a kit
// file for good). Only files that differ are written, and files the kit no longer has are removed: it is safe to run
// beside a running dev server (emptying the folder first left the server with missing files and a broken page).
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const from = resolve(dirname(fileURLToPath(import.meta.url)), '../src/lib');
const app = process.cwd();
const to = join(app, '.kit/lib');

if (!existsSync(join(app, 'package.json')) || resolve(app) === resolve(from, '../..')) {
	throw new Error(`kit-sync: run it from an app's frontend folder (through its \`npm run kit\`), not from ${app}`);
}

/** Every file under a folder, as paths relative to it. */
function filesIn(root) {
	if (!existsSync(root)) return [];
	const out = [];
	const walk = (dir) => {
		for (const name of readdirSync(dir)) {
			const path = join(dir, name);
			if (statSync(path).isDirectory()) walk(path);
			else out.push(relative(root, path));
		}
	};
	walk(root);
	return out;
}

const wanted = filesIn(from);
let written = 0;
for (const rel of wanted) {
	const [src, dst] = [join(from, rel), join(to, rel)];
	if (existsSync(dst) && readFileSync(src).equals(readFileSync(dst))) continue;
	mkdirSync(dirname(dst), { recursive: true });
	copyFileSync(src, dst);
	written++;
}
const keep = new Set(wanted);
let removed = 0;
for (const rel of filesIn(to)) {
	if (keep.has(rel)) continue;
	rmSync(join(to, rel));
	removed++;
}
console.log(`kit-sync: .kit is up to date (${written} written, ${removed} removed)`);
