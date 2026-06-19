#!/usr/bin/env node
// Vitest launcher that pins the drive-letter casing of the working directory before starting.
//
// On Windows a shell can launch with a lowercase drive (`d:\…`) while Node's module loader resolves
// the same files with the uppercase on-disk casing (`D:\…`). Under that split, vite-node loads
// `@vitest/runner` as two separate module instances, so the runner singleton the worker initialises
// isn't the one `describe` sees — every suite then fails at collection with
// "TypeError: Cannot read properties of undefined (reading 'config')" (vitest issue #5251).
//
// The cwd must already have the correct casing when the vitest process starts (fixing it later, e.g.
// from vite.config.ts, is too late — spec paths are resolved first). So we spawn vitest in a fresh
// child process whose cwd is normalised to the real on-disk casing. All args are passed through, so
// `node scripts/run-vitest.mjs run src/foo` behaves exactly like `vitest run src/foo`.
import { realpathSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

// Both the cwd AND the path we load vitest's bin from must use the real on-disk casing: if the bin
// path is lowercase, the child loads vitest's own modules (incl. @vitest/runner) under that casing
// while cwd is uppercase, re-creating the very split we're fixing. realpathSync.native normalises
// both to the on-disk casing so the runner stays a single module instance.
const require = createRequire(import.meta.url);
const vitestBin = realpathSync.native(join(dirname(require.resolve('vitest/package.json')), 'vitest.mjs'));
const cwd = realpathSync.native(process.cwd());

const result = spawnSync(process.execPath, [vitestBin, ...process.argv.slice(2)], {
  cwd,
  stdio: 'inherit'
});

if (result.error) {
  console.error(result.error);
  process.exit(1);
}
process.exit(result.status ?? 1);
