// Brings this app's copy of the shared UI kit (@hiroleague/ui) up to date with the kit folder of this repo (../ui-kit),
// which it sits beside. The kit is installed as a copy (.npmrc install-links), so it uses this app's own svelte and bits-ui;
// npm does not copy it again while its version stays the same, so dev, build, check and test start with this.
// (The same trap as the Python SDK's: a same-version local package served stale from a cache.)
import { cpSync, existsSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const from = resolve(here, '../../ui-kit/src/lib');
const to = resolve(here, '../node_modules/@hiroleague/ui/src/lib');
if (!existsSync(from)) {
	// e.g. the image's build after its packages were installed from a copy: nothing newer to bring
	console.log(`kit-sync: no kit at ${from}; keeping the installed copy`);
} else {
	rmSync(to, { recursive: true, force: true });
	cpSync(from, to, { recursive: true });
	console.log('kit-sync: @hiroleague/ui is up to date');
}
