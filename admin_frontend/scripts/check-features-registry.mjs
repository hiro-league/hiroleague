#!/usr/bin/env node
/** Fail when the committed feature registry is stale. */
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(__dirname, '..');

execFileSync('node', [path.join(__dirname, 'gen-features-registry.mjs')], {
  cwd: adminRoot,
  stdio: 'inherit'
});

try {
  execFileSync(
    'git',
    ['diff', '--exit-code', '--', 'src/lib/api/generated/feature-registry.json'],
    { cwd: adminRoot, stdio: 'inherit' }
  );
} catch {
  console.error(
    '\nFeature registry codegen is stale. Run `npm run gen:features` from admin_frontend and commit the result.'
  );
  process.exit(1);
}

console.log('Feature registry is up to date.');
