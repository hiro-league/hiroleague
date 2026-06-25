#!/usr/bin/env node
/** Fail when committed preferences codegen artifacts are stale. */
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(__dirname, '..');

execFileSync('node', [path.join(__dirname, 'gen-preferences-types.mjs')], {
  cwd: adminRoot,
  stdio: 'inherit'
});

const paths = [
  'schemas/workspace-preferences.schema.json',
  'src/lib/api/generated/preferences.generated.ts',
  'src/lib/api/generated/workspace-preferences.defaults.json',
  'src/lib/api/generated/workspace-preferences.defaults.ts',
  'src/lib/api/generated/preferences-field-schema.json',
  'src/lib/api/generated/preferences-paths.generated.ts'
];

try {
  execFileSync('git', ['diff', '--exit-code', '--', ...paths], {
    cwd: adminRoot,
    stdio: 'inherit'
  });
} catch {
  console.error(
    '\nPreferences codegen is stale. Run `npm run gen:prefs-types` from admin_frontend and commit the result.'
  );
  process.exit(1);
}

console.log('Preferences codegen is up to date.');
