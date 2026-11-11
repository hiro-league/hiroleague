// Where the kit is: the folder HIRO_KIT_DIR names (the kit's folder, .../ui-kit), else ../../../hiroleague/ui-kit
// (the app sits beside the HiroLeague checkout). Set HIRO_KIT_DIR when the checkouts are laid out differently.
//
// Brings this app's copy of the shared UI kit (@hiroleague/ui) up to date: the kit's src/lib, copied to .kit/lib
// (not committed; $kit points there: SvelteKit takes an alias ending in ".kit" for a file, hence the lib folder).
// dev, build, check and test start with this, so the copy is never stale.
// A copy, not a link, so the kit's files use this app's own svelte and bits-ui (one of each), and a folder of the
// app's own, not node_modules: the dev server watches it and reloads on a change (under node_modules the browser
// kept a kit file for good).
// Only files that differ are written, and files the kit no longer has are removed: it is safe to run beside a
// running dev server (emptying the folder first left the server with missing files and a broken page).
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const kitDir = process.env.HIRO_KIT_DIR ? resolve(process.env.HIRO_KIT_DIR) : resolve(here, '../../../hiroleague/ui-kit');
const from = join(kitDir, 'src/lib');
const to = resolve(here, '../.kit/lib');

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

if (!existsSync(from)) {
	if (!existsSync(to)) throw new Error(`kit-sync: no kit at ${from} and no copy at ${to}. Put this app beside the HiroLeague checkout (../../../hiroleague/ui-kit), or set HIRO_KIT_DIR to the kit's folder.`);
	console.log(`kit-sync: no kit at ${from}; keeping the copy`);
} else {
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
}
