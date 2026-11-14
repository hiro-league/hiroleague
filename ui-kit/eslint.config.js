// Lint (npm run lint, also part of npm run check): the setup every Hiro frontend shares (src/lib/eslint-preset.js, the
// same one the apps use from their .kit copy). shadcn's components (src/lib/components/ui/) are added with its CLI and
// kept as it writes them; the kit has no "shared layers never import a feature" rule, it has no features.
import { defineConfig } from 'eslint/config';
import { hiroEslint } from './src/lib/eslint-preset.js';

export default defineConfig(...hiroEslint({ dirname: import.meta.dirname, ignores: ['src/lib/components/ui/'] }));
