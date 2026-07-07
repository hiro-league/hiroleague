#!/usr/bin/env node
/**
 * Regenerate the frontend feature registry from the backend Python ledger.
 *
 * The ledger (hirocli/domain/features.py) is the single source of truth for which
 * features are exposed. This emits a synchronously-importable copy for the SPA so
 * nav filtering and route guards can read it at module-load time.
 *
 * Output (committed):
 * - src/lib/api/generated/feature-registry.json
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(adminRoot, '..');
const hirocliRoot = path.join(repoRoot, 'hiroserver', 'hirocli');

const generatedDir = path.join(adminRoot, 'src', 'lib', 'api', 'generated');
const outPath = path.join(generatedDir, 'feature-registry.json');

mkdirSync(generatedDir, { recursive: true });

execFileSync(
  'uv',
  ['run', 'python', path.join(hirocliRoot, 'scripts', 'emit_features_codegen.py'), '--out', outPath],
  { cwd: hirocliRoot, stdio: 'inherit' }
);

console.log('Generated feature registry.');
